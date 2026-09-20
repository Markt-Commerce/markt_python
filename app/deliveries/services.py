# python imports
import logging
import uuid
import math
from datetime import datetime
from random import randint
from typing import Dict, List, Optional

# flask imports
from flask_login import current_user

# package imports
from app.users.models import User, Seller, UserAddress, Buyer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from sqlalchemy.orm import joinedload

# project imports
from external.redis import redis_client
from app.libs.session import session_scope
from app.libs.pagination import Paginator
from app.libs.errors import (
    APIError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.libs.email_service import email_service

# app imports
from .models import (
    DeliveryUser,
    DeliveryLastLocation,
    DeliveryOrderAssignment,
    DeliveryStatus,
    DeliveryVehicleType,
    AssignmentStatus,
    LogisticalStatus,
    LocationUpdateRoom,
    OrderLocationMapping,
)
from app.notifications.models import NotificationType
from app.notifications.services import NotificationService
from app.delivery_pricing.order_delivery import (
    DeliveryState,
    advance_buyer_delivery,
)
from app.orders.events import ActorType, OrderEventService, OrderEventType
from app.orders.models import Order, OrderItem, OrderStatus, ShippingAddress
from app.orders.services import OrderService
from app.deliveries import offers
from app.deliveries.rider_pay import earning_for_drop
from app.wallet.services import WalletService

logger = logging.getLogger(__name__)


def _normalize_phone(raw: str) -> str:
    """Strip leading + and return digits-only; empty if invalid."""
    if not raw:
        return ""
    return (raw or "").lstrip("+").strip()


def _mask_email(email: str) -> str:
    """Enough of an address to recognise your own inbox, not enough to be
    somebody else's.

    The OTP endpoint used to answer with the address in full -- "OTP sent to
    ada@example.com" -- to anyone who posted a phone number. A rider's phone
    number is on every package they deliver, so that turned a delivery note
    into a lookup for their personal email. It is also the one response you
    do not need authentication to reach.
    """
    if not email or "@" not in email:
        return "your email"
    name, _, domain = email.partition("@")
    head = name[0] if name else ""
    return f"{head}{'*' * max(len(name) - 1, 1)}@{domain}"


class DeliveryService:

    # Ten minutes: long enough for an email to arrive and be typed out,
    # short enough that a code left sitting in an inbox stops working. It
    # was an hour, "relaxed for tests", which is the kind of relaxation that
    # ships.
    CACHE_EXPIRE_SECONDS = 600
    CACHE_KEY_PREFIX = "otp_cache:"
    PHONE_MIN_LEN = 10
    PHONE_MAX_LEN = 15

    # defined valid status transitions for LogisticalStatus
    VALID_STATUS_TRANSITIONS = {
        None: [
            LogisticalStatus.ARRIVED_PICKUP
        ],  # initial status can only be ARRIVED_PICKUP
        LogisticalStatus.ARRIVED_PICKUP: [LogisticalStatus.PICKED_UP],
        LogisticalStatus.PICKED_UP: [LogisticalStatus.EN_ROUTE_TO_DROPOFF],
        LogisticalStatus.EN_ROUTE_TO_DROPOFF: [LogisticalStatus.DELIVERED_PENDING_QR],
        LogisticalStatus.DELIVERED_PENDING_QR: [LogisticalStatus.COMPLETED],
        LogisticalStatus.COMPLETED: [],  # final state
    }

    @staticmethod
    def login_delivery_partner(phone_number: str, otp: str) -> Dict:
        """Authenticate delivery partner and return partner details"""

        phone = _normalize_phone(phone_number)
        if (
            not phone
            or not phone.isdigit()
            or len(phone) < DeliveryService.PHONE_MIN_LEN
            or len(phone) > DeliveryService.PHONE_MAX_LEN
        ):
            logger.warning(f"Invalid phone number format: {phone_number}")
            raise ValidationError("Invalid phone number format")
        cache_key = f"{DeliveryService.CACHE_KEY_PREFIX}{phone}"
        cached_otp = redis_client.get(cache_key)
        cached_str = (
            cached_otp.decode() if isinstance(cached_otp, bytes) else cached_otp
        )
        if not cached_otp or cached_str != otp:
            logger.warning(f"Invalid OTP for phone number {phone_number}")
            raise ValidationError("Invalid OTP")

        # Spend it. A code that survives being used is a password with an
        # hour's life on it: it sits in a mailbox, and anyone who reads that
        # mailbox -- a forwarded message, a shared laptop, a shoulder on a
        # bus -- can sign in as this rider repeatedly until it expires.
        # Deleting before the lookup rather than after is deliberate: if the
        # partner turns out not to exist, the code is still spent, so a
        # wrong-number guess cannot be retried against a working code.
        redis_client.delete(cache_key)

        try:
            with session_scope() as session:
                delivery_user = (
                    session.query(DeliveryUser).filter_by(phone_number=phone).first()
                )
                if not delivery_user:
                    logger.warning(
                        f"No delivery partner found with phone number {phone_number}"
                    )
                    raise NotFoundError("Delivery partner not found")

                # Return user for route to call login_user (same pattern as users/login)
                return delivery_user
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            raise NotFoundError(
                "Login failed due to invalid credentials or server error"
            )

    @staticmethod
    def update_partner(user_id: str, data: Dict) -> Dict:
        """Change the handful of things a rider owns about themselves.

        Deliberately not phone number or status: the phone is the login
        credential and changing it needs the OTP flow, and status is what
        the online/offline toggle already owns.
        """
        allowed = {}
        if "name" in data and data["name"]:
            name = str(data["name"]).strip()
            if not name:
                raise ValidationError("Name cannot be empty")
            allowed["name"] = name[:100]
        if "vehicle_type" in data and data["vehicle_type"]:
            try:
                allowed["vehicle_type"] = DeliveryVehicleType(data["vehicle_type"])
            except ValueError:
                raise ValidationError("Unknown vehicle type")
        if "email" in data and data["email"]:
            allowed["email"] = str(data["email"]).strip()[:100]

        if not allowed:
            raise ValidationError("Nothing to update")

        with session_scope() as session:
            rider = session.query(DeliveryUser).get(user_id)
            if not rider:
                raise NotFoundError("Delivery partner not found")
            for field, value in allowed.items():
                setattr(rider, field, value)
            session.flush()
            return {
                "id": rider.id,
                "name": rider.name,
                "email": rider.email,
                "phone_number": rider.phone_number,
                "status": rider.status.value if rider.status else None,
                "vehicle_type": (
                    rider.vehicle_type.value if rider.vehicle_type else None
                ),
                "rating": rider.rating,
                "profile_picture": rider.profile_picture,
            }

    @staticmethod
    def upload_profile_picture(user_id: str, file_stream, filename: str) -> Dict:
        """Set the rider's photo, replacing any previous one.

        A near-twin of UserService.upload_profile_picture rather than a
        shared generic, for the same reason upload_shop_banner is: the two
        differ in which table the URL lands on, and folding them together
        would put a "which kind of account is this" branch inside every
        step. The media row itself knows -- see media.delivery_user_id.
        """
        from io import BytesIO
        from urllib.parse import urlparse

        from app.media.models import Media, MediaVariant
        from app.media.services import media_service

        if not isinstance(file_stream, BytesIO):
            file_stream = BytesIO(file_stream.read())

        with session_scope() as session:
            rider = session.query(DeliveryUser).get(user_id)
            if not rider:
                raise NotFoundError("Delivery partner not found")

            # Drop the previous photo, or every re-upload leaks a file in
            # S3 and a row in media.
            if rider.profile_picture:
                storage_key = urlparse(rider.profile_picture).path.lstrip("/")
                old = session.query(Media).filter_by(storage_key=storage_key).first()
                if old:
                    try:
                        media_service.delete_media(old)
                    except Exception:
                        # A file we cannot delete must not stop a rider
                        # replacing their photo.
                        logger.warning(
                            "Could not remove old rider photo %s", storage_key
                        )
                    session.query(MediaVariant).filter_by(media_id=old.id).delete()
                    session.delete(old)
                rider.profile_picture = None

        media = media_service.upload_image(
            file_stream=file_stream,
            filename=filename,
            user_id=user_id,
            alt_text=f"Profile picture for delivery partner {user_id}",
            caption="Profile picture",
            is_profile_picture=True,
        )

        with session_scope() as session:
            rider = session.query(DeliveryUser).get(user_id)
            if not rider:
                raise NotFoundError("Delivery partner not found")
            rider.profile_picture = media.get_url()
            url = rider.profile_picture

        return {"profile_picture": url}

    @staticmethod
    def send_otp(phone_number: str) -> bool:
        """Generate and send OTP to delivery partner's email (phone number would be used later when we integrate SMS service)"""
        try:
            phone = _normalize_phone(phone_number)
            if (
                not phone
                or not phone.isdigit()
                or len(phone) < DeliveryService.PHONE_MIN_LEN
                or len(phone) > DeliveryService.PHONE_MAX_LEN
            ):
                raise ValidationError("Invalid phone number format")

            otp = f"{randint(100000, 999999)}"

            with session_scope() as session:
                delivery_user = (
                    session.query(DeliveryUser).filter_by(phone_number=phone).first()
                )
                if not delivery_user:
                    logger.warning(
                        f"No delivery partner found with phone number {phone_number}"
                    )
                    raise NotFoundError("Delivery partner not found")

                email = delivery_user.email
                if not email:
                    logger.warning(
                        f"No email found for delivery partner with phone number {phone_number}"
                    )
                    raise NotFoundError("Email not found")

            # The code itself is deliberately not logged. It used to be,
            # which put a working credential into every log sink, aggregator
            # and support screenshot that touches this line.
            logger.info("Sending OTP to %s", email)
            if email_service.send_otp_email(email, otp):
                cache_key = f"{DeliveryService.CACHE_KEY_PREFIX}{phone}"
                redis_client.setex(cache_key, DeliveryService.CACHE_EXPIRE_SECONDS, otp)
                return {
                    "status": "success",
                    "message": f"OTP sent to {_mask_email(email)}",
                }
            else:
                logger.error(f"Failed to send OTP email to {email}")
                return {
                    "status": "error",
                    "message": (
                        "We could not deliver a code to the email on this "
                        "account. Contact support."
                    ),
                }
        except Exception as e:
            logger.error(f"Error sending OTP: {str(e)}")
            return {"status": "error", "message": "Failed to send OTP", "error": str(e)}

    @staticmethod
    def register_delivery_partner(data: Dict) -> Dict:
        """Register a new delivery partner. Phone stored normalized (digits only)."""
        try:
            phone = _normalize_phone(data.get("phone_number") or "")
            if (
                not phone
                or not phone.isdigit()
                or len(phone) < DeliveryService.PHONE_MIN_LEN
                or len(phone) > DeliveryService.PHONE_MAX_LEN
            ):
                logger.warning(
                    f"Invalid phone number format: {data.get('phone_number')}"
                )
                raise ValidationError("Invalid phone number format")

            if not data.get("email") or "@" not in data["email"]:
                logger.warning(f"Invalid email format: {data.get('email')}")
                raise ValidationError("Invalid email format")

            if not data.get("name"):
                logger.warning("Name is required for registration")
                raise ValidationError("Name is required")

            with session_scope() as session:
                existing_partner = (
                    session.query(DeliveryUser)
                    .filter(
                        (DeliveryUser.phone_number == phone)
                        | (DeliveryUser.email == data["email"])
                    )
                    .first()
                )
                if existing_partner:
                    logger.warning(
                        f"Delivery partner with phone number or email already exists"
                    )
                    raise ValidationError(
                        "Delivery partner already registered, Delivery partner with this phone number or email already exists"
                    )

                new_partner = DeliveryUser(
                    phone_number=phone,
                    email=data.get("email"),
                    name=data["name"],
                    status=DeliveryStatus.INACTIVE,  # New partners start as INACTIVE until they complete onboarding
                    vehicle_type=(
                        DeliveryVehicleType[data.get("vehicle_type").upper()]
                        if data.get("vehicle_type")
                        and data.get("vehicle_type").upper()
                        in [e.name for e in DeliveryVehicleType]
                        else DeliveryVehicleType.BIKE
                    ),
                )
                session.add(new_partner)
                session.commit()

                return {
                    "id": new_partner.id,
                    "name": new_partner.name,
                    "status": new_partner.status.value,
                    "vehicle_type": (
                        new_partner.vehicle_type.value
                        if new_partner.vehicle_type
                        else None
                    ),
                }
        except Exception as e:
            logger.error(f"Error registering delivery partner: {str(e)}")
            raise ValidationError(f"Failed to register delivery partner")

    @staticmethod
    def get_current_delivery_partner(user_id: str) -> Dict:
        """Get current delivery partner details. user_id is the DeliveryUser.id from session."""
        try:
            with session_scope() as session:
                delivery_user = (
                    session.query(DeliveryUser).filter_by(id=user_id).first()
                )
                if not delivery_user:
                    logger.warning(f"No delivery partner found for user ID {user_id}")
                    raise NotFoundError("Delivery partner not found")

                return {
                    "id": delivery_user.id,
                    "name": delivery_user.name,
                    "status": delivery_user.status.value,
                    "vehicle_type": (
                        delivery_user.vehicle_type.value
                        if delivery_user.vehicle_type
                        else None
                    ),
                    "rating": delivery_user.rating,
                    "email": delivery_user.email,
                    "phone_number": delivery_user.phone_number,
                    "profile_picture": delivery_user.profile_picture,
                }
        except Exception as e:
            logger.error(f"Error fetching current delivery partner: {str(e)}")
            raise NotFoundError("Failed to fetch delivery partner")

    @staticmethod
    def update_delivery_partner_status(user_id: str) -> Dict:
        """Update current delivery partner status. user_id is the DeliveryUser.id from session."""
        try:
            with session_scope() as session:
                delivery_user = (
                    session.query(DeliveryUser).filter_by(id=user_id).first()
                )
                if not delivery_user:
                    logger.warning(f"No delivery partner found for user ID {user_id}")
                    raise NotFoundError("Delivery partner not found")

                if delivery_user.status == DeliveryStatus.ACTIVE:
                    delivery_user.status = DeliveryStatus.INACTIVE
                elif delivery_user.status == DeliveryStatus.INACTIVE:
                    delivery_user.status = DeliveryStatus.ACTIVE

                session.add(delivery_user)
                session.commit()

                return {"status": delivery_user.status.value}
        except Exception as e:
            logger.error(f"Error updating delivery partner status: {str(e)}")
            raise NotFoundError("Failed to update status")

    @staticmethod
    def update_delivery_partner_location(
        user_id: str, location: Dict[str, float]
    ) -> Dict:
        """Update delivery partner location. user_id is the DeliveryUser.id from session."""
        try:
            with session_scope() as session:
                delivery_user = (
                    session.query(DeliveryUser).filter_by(id=user_id).first()
                )

                if not delivery_user:
                    logger.warning(f"No delivery partner found for user ID {user_id}")
                    raise NotFoundError("Delivery partner not found")

                last_location = (
                    session.query(DeliveryLastLocation)
                    .filter_by(delivery_user_id=delivery_user.id)
                    .first()
                )

                if last_location:
                    # UPDATE existing row
                    last_location.latitude = location["lat"]
                    last_location.longitude = location["lng"]
                    last_location.accuracy = location.get("accuracy")
                    last_location.speed = location.get("speed")
                else:
                    # CREATE row
                    last_location = DeliveryLastLocation(
                        delivery_user_id=delivery_user.id,
                        latitude=location["lat"],
                        longitude=location["lng"],
                        accuracy=location.get("accuracy"),
                        speed=location.get("speed"),
                    )
                    session.add(last_location)

                session.commit()

        except Exception as e:
            logger.error(f"Error updating delivery partner location: {str(e)}")
            raise NotFoundError("Failed to update location")

        return {"status": "success", "message": "Location updated"}

    # slightly complex functionality
    # we would need, after the MVP, to optimize this
    # either by using postGIS to calculate the distance properly,
    # or by pre-calculating the distance between the delivery partner and the sellers and caching that in Redis, and then just fetching the available orders based on the cached distances

    @staticmethod
    def get_available_orders(
        user_id: str,
        search_radius: int = 5000,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """Get available orders for the delivery partner with pagination.
        per_page is capped at 50.
        """
        per_page = min(max(1, per_page), 50)
        page = max(1, page)

        try:
            with session_scope() as session:
                delivery_user = (
                    session.query(DeliveryUser)
                    .filter(DeliveryUser.id == user_id)
                    .first()
                )

                # error handling for delivery user not found, suspended, or missing location
                if not delivery_user:
                    raise NotFoundError("Delivery partner not found")

                if delivery_user.status == DeliveryStatus.SUSPENDED:
                    raise ForbiddenError("Your account has been suspended")

                if (
                    not delivery_user.last_location
                    or delivery_user.last_location.latitude is None
                    or delivery_user.last_location.longitude is None
                ):
                    raise ValidationError(
                        "Location not set. Please update your location before browsing available orders."
                    )

                delivery_lat = delivery_user.last_location.latitude
                delivery_lng = delivery_user.last_location.longitude

                orders = (
                    session.query(Order)
                    .filter(Order.status == OrderStatus.READY_FOR_DELIVERY)
                    .options(
                        joinedload(Order.shipping_address),
                        joinedload(Order.items)
                        .joinedload(OrderItem.seller)
                        .joinedload(Seller.user)
                        .joinedload(User.address),
                    )
                    .all()
                )

                # What is genuinely available to *this* rider.
                #
                # This list used to be every order in READY_FOR_DELIVERY with
                # no reference to assignments at all. Accepting an order does
                # not change its status, so an order another rider was already
                # carrying stayed on everyone's list until it was delivered --
                # tapping it returned "Order already accepted" and the real
                # work was buried under it. A rider's own declines sat there
                # too, equally untakeable.
                assignment_rows = (
                    session.query(DeliveryOrderAssignment)
                    .filter(
                        DeliveryOrderAssignment.order_id.in_(
                            [order.id for order in orders]
                        )
                    )
                    .all()
                    if orders
                    else []
                )

                at = offers.now()
                taken = set()
                hidden_from_me = set()
                for row in assignment_rows:
                    if row.status == AssignmentStatus.ACCEPTED:
                        taken.add(row.order_id)
                    elif offers.is_live_offer(row, at):
                        # Held by someone right now -- including, briefly,
                        # this rider, whose own countdown screen is showing
                        # it rather than the list.
                        hidden_from_me.add(row.order_id)
                    elif (
                        row.delivery_user_id == user_id
                        and offers.suppresses_for_rider(row, at)
                    ):
                        hidden_from_me.add(row.order_id)

                orders = [
                    order
                    for order in orders
                    if order.id not in taken and order.id not in hidden_from_me
                ]

                available_orders = []

                for order in orders:
                    dropoff = order.shipping_address

                    if (
                        not dropoff
                        or dropoff.latitude is None
                        or dropoff.longitude is None
                    ):
                        continue

                    if not order.items:
                        continue

                    seller_pickups = []
                    pickup_distances = []
                    seen_seller_ids = set()

                    pickup_sellers = []

                    for item in order.items:
                        seller = item.seller
                        if not seller or seller.id in seen_seller_ids:
                            continue

                        seen_seller_ids.add(seller.id)

                        # The shop's own coordinates first.
                        #
                        # This read seller.user.address and nothing else, but
                        # that is a personal address on the User, not the
                        # shop: sellers set where their shop is through
                        # Seller.shop_latitude/shop_longitude, which is what
                        # the delivery quote prices against, what the
                        # proximity feed ranks by, and what the run schemas
                        # hand the rider app to draw a pickup pin.
                        #
                        # So a seller who had set their shop location the
                        # supported way, and had no separate personal address
                        # row, was skipped -- their paid orders never appeared
                        # to any rider, and the only symptom was an available
                        # list that stayed empty.
                        pickup_lat = seller.shop_latitude
                        pickup_lng = seller.shop_longitude

                        if pickup_lat is None or pickup_lng is None:
                            seller_address = (
                                getattr(seller.user, "address", None)
                                if seller.user
                                else None
                            )
                            if seller_address:
                                pickup_lat = seller_address.latitude
                                pickup_lng = seller_address.longitude

                        if pickup_lat is None or pickup_lng is None:
                            continue

                        seller_pickups.append({"lat": pickup_lat, "lng": pickup_lng})
                        pickup_sellers.append(seller)

                        distance = DeliveryService.haversine_distance(
                            delivery_lat, delivery_lng, pickup_lat, pickup_lng
                        )
                        pickup_distances.append(distance)

                    if not seller_pickups:
                        continue

                    # Better than average for multi-pickup feasibility
                    max_distance = max(pickup_distances)

                    if max_distance > search_radius:
                        continue

                    # What the rider is actually credited on completion, not
                    # the buyer's shipping fee. Those were the same number
                    # until riders started taking a share of the trip rather
                    # than all of it, and this is the figure a rider decides
                    # on -- promising the fee and paying the share is the
                    # worst kind of wrong to be.
                    estimated_earnings = (
                        earning_for_drop(order.shipping_fee, stops=1) or 0
                    )

                    # What the rider is deciding on.
                    #
                    # This carried two coordinates, a distance and a number
                    # of naira -- so the accept card could only say "Order
                    # #a1b2c3d4", and a rider had no way to tell a pickup
                    # from a shop they know from one down an alley they
                    # don't. The name, the street and the shop's picture
                    # are what makes the offer legible, and they are the
                    # same three the assignment already hands over *after*
                    # accepting; withholding them until then is asking for
                    # a decision without the facts behind it.
                    first_seller = pickup_sellers[0] if pickup_sellers else None

                    available_orders.append(
                        {
                            "order_id": order.id,
                            "order_number": order.order_number,
                            "pickup": seller_pickups,
                            "dropoff": {
                                "lat": dropoff.latitude,
                                "lng": dropoff.longitude,
                            },
                            "distance_meters": round(max_distance, 2),
                            "estimated_earnings": estimated_earnings,
                            "seller_name": (
                                getattr(first_seller, "shop_name", None)
                                if first_seller
                                else None
                            ),
                            "seller_image": DeliveryService._shop_image(first_seller),
                            "pickup_address": DeliveryService._shop_address_line(
                                first_seller
                            ),
                            # A second shop is a second stop, and that is
                            # the difference between a ten-minute job and a
                            # half-hour one.
                            "pickup_count": len(seller_pickups),
                            "item_count": sum(
                                (item.quantity or 1) for item in order.items
                            ),
                            # Where they are taking it. Not the full address
                            # -- that is the buyer's, and they have not
                            # accepted yet -- just the area, which is what
                            # tells them whether it is a trip home or the
                            # wrong way across town.
                            "dropoff_area": getattr(dropoff, "city", None),
                        }
                    )

                total = len(available_orders)
                start = (page - 1) * per_page
                end = start + per_page
                page_orders = available_orders[start:end]

                return {
                    "range_meters": search_radius,
                    "orders": page_orders,
                    "page": page,
                    "per_page": per_page,
                    "total": total,
                    "total_pages": (total + per_page - 1) // per_page if total else 0,
                }
        except (NotFoundError, ForbiddenError, ValidationError):
            raise
        except SQLAlchemyError as e:
            logger.exception(f"Database error fetching available orders: {str(e)}")
            raise APIError(
                "Database error while fetching available orders", status_code=500
            )
        except Exception as e:
            logger.exception(f"Unexpected error fetching available orders: {str(e)}")
            raise APIError("Failed to fetch available orders", status_code=500)

    @staticmethod
    def haversine_distance(lat1, lng1, lat2, lng2):
        R = 6371000  # Earth radius in meters

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lng2 - lng1)

        a = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )

        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    @staticmethod
    def offer_order(user_id: str, order_id: str) -> Dict:
        """Hold this order for this rider while they decide.

        The countdown in the app is only meaningful if the order is really
        held, so this is what the app calls when a rider opens one. It
        returns the expiry, and the app counts down to *that* -- the
        server's clock, not the phone's, which can be minutes out and is
        the rider's to change.
        """
        with session_scope() as session:
            at = offers.now()
            rows = (
                session.query(DeliveryOrderAssignment)
                .filter_by(order_id=order_id)
                .with_for_update()
                .all()
            )

            if any(r.status == AssignmentStatus.ACCEPTED for r in rows):
                raise ConflictError("Someone else already took this order")

            held_by_other = next(
                (
                    r
                    for r in rows
                    if r.delivery_user_id != user_id and offers.is_live_offer(r, at)
                ),
                None,
            )
            if held_by_other:
                raise ConflictError("Another rider is looking at this order")

            mine = next((r for r in rows if r.delivery_user_id == user_id), None)
            if mine is None:
                mine = DeliveryOrderAssignment(
                    delivery_user_id=user_id,
                    order_id=order_id,
                    assignment_id=str(uuid.uuid4()),
                    status=AssignmentStatus.OFFERED,
                )
                session.add(mine)
            else:
                # Re-offering to a rider who declined earlier is fine once
                # the cooldown is over -- that is the whole point of the
                # cooldown -- but not while it is still running.
                if offers.suppresses_for_rider(mine, at) and not offers.is_live_offer(
                    mine, at
                ):
                    raise ConflictError("You passed on this order recently")
                mine.status = AssignmentStatus.OFFERED

            expires_at = offers.offer_expiry(at)
            mine.expires_at = expires_at
            session.flush()

            return {
                "assignment_id": mine.assignment_id,
                "status": mine.status.value,
                "expires_at": expires_at.isoformat() + "Z",
                "seconds": offers.OFFER_SECONDS,
            }

    @staticmethod
    def accept_order(user_id: str, order_id: str) -> Dict:
        with session_scope() as session:
            at = offers.now()
            assignments = (
                session.query(DeliveryOrderAssignment)
                .filter_by(order_id=order_id)
                .with_for_update()
                .all()
            )
            if any(a.status == AssignmentStatus.ACCEPTED for a in assignments):
                logger.warning(
                    f"Order {order_id} has already been accepted by another delivery partner"
                )
                raise ConflictError("Someone else already took this order")

            held_by_other = next(
                (
                    a
                    for a in assignments
                    if a.delivery_user_id != user_id and offers.is_live_offer(a, at)
                ),
                None,
            )
            if held_by_other:
                raise ConflictError("Another rider is looking at this order")

            mine = next((a for a in assignments if a.delivery_user_id == user_id), None)

            # How many they are already carrying. Unlimited before, so a
            # rider could take every order on the dashboard and leave four
            # of five buyers watching an order that was "on its way" and
            # going cold. See offers.MAX_CONCURRENT_ORDERS.
            carrying = (
                session.query(DeliveryOrderAssignment)
                .filter(
                    DeliveryOrderAssignment.delivery_user_id == user_id,
                    DeliveryOrderAssignment.order_id != order_id,
                    DeliveryOrderAssignment.status == AssignmentStatus.ACCEPTED,
                    (DeliveryOrderAssignment.logistical_status.is_(None))
                    | (
                        DeliveryOrderAssignment.logistical_status
                        != LogisticalStatus.COMPLETED
                    ),
                )
                .count()
            )
            if carrying >= offers.MAX_CONCURRENT_ORDERS:
                raise ConflictError(
                    "Finish what you are carrying before taking another. "
                    f"You have {carrying}."
                )

            # A rider inside a decline cooldown cannot accept. A rider whose
            # offer merely lapsed can: they were looking at it a moment ago,
            # and refusing them now -- when nobody else has taken it -- would
            # be leaving an order on the ground to enforce a technicality.
            if (
                mine is not None
                and mine.status == AssignmentStatus.REJECTED
                and offers.suppresses_for_rider(mine, at)
            ):
                raise ConflictError("You passed on this order recently")

            if mine is None:
                mine = DeliveryOrderAssignment(
                    delivery_user_id=user_id,
                    order_id=order_id,
                    assignment_id=str(uuid.uuid4()),
                    status=AssignmentStatus.ACCEPTED,
                )
                session.add(mine)
            else:
                mine.status = AssignmentStatus.ACCEPTED

            mine.escrow_qr_code = mine.escrow_qr_code or str(uuid.uuid4())
            mine.expires_at = None
            session.flush()

            # The buyer's tracker has a "Rider assigned" step and nothing
            # was ever reaching it.
            advance_buyer_delivery(session, order_id, DeliveryState.ASSIGNED)

            audience = DeliveryService._delivery_audience(session, mine)
            result = {
                "status": AssignmentStatus.ASSIGNED.value,
                "assignment_id": mine.assignment_id,
            }

        # The first thing either side hears about the delivery. A buyer
        # watching a paid order had no way to know a rider had been found
        # short of opening the app and pulling to refresh, and the seller
        # got no warning at all that someone was on their way to a
        # collection they have to be there for.
        DeliveryService._send_delivery_notice(
            audience,
            buyer_text="{rider} is on the way to collect order {order}.",
            seller_text="{rider} is on the way to collect order {order} from your shop.",
            status_value="ACCEPTED",
        )

        return result

    @staticmethod
    def reject_order(user_id: str, order_id: str) -> Dict:
        """Pass on an order -- for now, not forever.

        A decline used to be permanent: the rider could never see the order
        again, and nothing anywhere put it back. Three riders in an area
        declining once each made the order invisible to all of them with no
        way to recover it. It is a cooldown now.
        """
        with session_scope() as session:
            at = offers.now()
            assignments = (
                session.query(DeliveryOrderAssignment)
                .filter_by(order_id=order_id)
                .with_for_update()
                .all()
            )
            if any(a.status == AssignmentStatus.ACCEPTED for a in assignments):
                raise ConflictError("Someone else already took this order")

            mine = next((a for a in assignments if a.delivery_user_id == user_id), None)
            if mine is None:
                mine = DeliveryOrderAssignment(
                    delivery_user_id=user_id,
                    order_id=order_id,
                    assignment_id=str(uuid.uuid4()),
                    status=AssignmentStatus.REJECTED,
                )
                session.add(mine)
            else:
                mine.status = AssignmentStatus.REJECTED

            mine.escrow_qr_code = None
            mine.expires_at = offers.decline_until(at)
            session.flush()

            return {
                "status": AssignmentStatus.REJECTED.value,
                "assignment_id": mine.assignment_id,
                "available_again_at": mine.expires_at.isoformat() + "Z",
            }

    @staticmethod
    def get_active_assignments(user_id: str) -> Dict:
        with session_scope() as session:
            # ACCEPTED is the assignment's status for the whole job and
            # never changes, so a delivery the rider finished stayed in
            # "My active deliveries" forever, wearing a Completed pill,
            # pushing the actual work off the bottom of the screen. The
            # step is what says whether it is still live.
            active_assignments = (
                session.query(DeliveryOrderAssignment)
                .filter(
                    DeliveryOrderAssignment.delivery_user_id == user_id,
                    DeliveryOrderAssignment.status == AssignmentStatus.ACCEPTED,
                    (DeliveryOrderAssignment.logistical_status.is_(None))
                    | (
                        DeliveryOrderAssignment.logistical_status
                        != LogisticalStatus.COMPLETED
                    ),
                )
                # Eagerly load the order and its nested relationships
                .options(
                    joinedload(DeliveryOrderAssignment.order).joinedload(
                        Order.shipping_address
                    ),
                    # Through to the product, since the manifest names
                    # each line -- otherwise this is one query per item.
                    joinedload(DeliveryOrderAssignment.order)
                    .joinedload(Order.items)
                    .joinedload(OrderItem.product),
                    joinedload(DeliveryOrderAssignment.order)
                    .joinedload(Order.items)
                    .joinedload(OrderItem.variant),
                    # _assignment_parties walks the seller and the buyer
                    # through to their User rows for the shop name, the
                    # two phone numbers and the pickup address, and
                    # get_assignment_pickups_from_order_item falls back
                    # to the seller's personal address for coordinates.
                    # None of it was loaded, so a rider carrying two
                    # deliveries paid for about a dozen extra round
                    # trips every time this list refreshed.
                    joinedload(DeliveryOrderAssignment.order)
                    .joinedload(Order.items)
                    .joinedload(OrderItem.seller)
                    .joinedload(Seller.user)
                    .joinedload(User.address),
                    joinedload(DeliveryOrderAssignment.order)
                    .joinedload(Order.buyer)
                    .joinedload(Buyer.user),
                )
                .all()
            )

            return {
                "assignments": [
                    {
                        "assignment_id": assignment.assignment_id,
                        "order_id": assignment.order_id,
                        "assigned_at": assignment.assigned_at,
                        "status": assignment.status.value,
                        # The status that actually moves.
                        #
                        # `status` is the *assignment* status, and for
                        # everything a rider does after accepting it is the
                        # constant ACCEPTED. The step they are on -- arrived,
                        # picked up, en route -- lives on logistical_status,
                        # and it was never sent. So the app had nothing to
                        # tell the steps apart by: it re-rendered "Arrived at
                        # pickup" after the rider had already arrived, and
                        # tapping it again was rejected by
                        # is_valid_status_transition (ARRIVED_PICKUP is only
                        # reachable from None) as an error the rider could do
                        # nothing about.
                        "logistical_status": (
                            assignment.logistical_status.value
                            if assignment.logistical_status
                            else None
                        ),
                        "pickup": DeliveryService.get_assignment_pickups_from_order_item(
                            assignment.order
                        ),
                        "dropoff": {
                            "lat": assignment.order.shipping_address.latitude,
                            "lng": assignment.order.shipping_address.longitude,
                        },
                        # Who and where, not just two coordinates. A rider
                        # was shown "Pickup from seller" with no name, no
                        # address and no way to call anyone -- a run's stops
                        # have carried all three since runs existed, and a
                        # single order is the same job with one stop.
                        **DeliveryService._assignment_parties(assignment.order),
                    }
                    for assignment in active_assignments
                ]
            }

    @staticmethod
    def _parcel_manifest(order) -> List[Dict]:
        """What the rider is collecting, line by line.

        A rider was told "3 items" and sent to a stall. There is no way to
        check that against what is handed over, so the only thing standing
        between a buyer and the wrong parcel was the shopkeeper
        remembering which bag was which.

        This is the pickup-side equivalent of the delivery code: the
        order number identifies the parcel, and the lines let the rider
        confirm the contents before they accept responsibility for them.
        """
        lines = []
        for item in getattr(order, "items", None) or []:
            status = getattr(item, "status", None)
            # A cancelled line is not in the bag, and listing it would
            # have the rider hunting for something nobody packed.
            if status is not None and status == OrderItem.Status.CANCELLED:
                continue

            product = getattr(item, "product", None)
            variant = getattr(item, "variant", None)
            lines.append(
                {
                    "name": getattr(product, "name", None) or "Item",
                    "quantity": getattr(item, "quantity", None) or 1,
                    "variant": getattr(variant, "name", None),
                }
            )
        return lines

    # What a rider can filter their own history by. Deliberately their
    # words rather than the enum's: a rider thinks "did I deliver it or
    # did something go wrong", not in terms of LogisticalStatus members.
    JOB_FILTERS = {
        "active": "Still carrying",
        "completed": "Delivered",
    }

    @staticmethod
    def get_job_history(
        user_id: str, status: Optional[str] = None, page: int = 1, per_page: int = 20
    ) -> Dict:
        """Every delivery this rider has taken, newest first.

        There was no way to see past work at all. The active list is the
        only assignment endpoint, and it shows what a rider is carrying
        right now -- so a rider asking "what did I deliver on Tuesday",
        or checking a payout that looks short, had the earnings ledger
        and nothing to tie its rows back to. The wallet says a number
        arrived; this says which job it was for.
        """
        with session_scope() as session:
            query = session.query(DeliveryOrderAssignment).filter(
                DeliveryOrderAssignment.delivery_user_id == user_id,
                DeliveryOrderAssignment.status == AssignmentStatus.ACCEPTED,
            )

            if status == "completed":
                query = query.filter(
                    DeliveryOrderAssignment.logistical_status
                    == LogisticalStatus.COMPLETED
                )
            elif status == "active":
                query = query.filter(
                    (DeliveryOrderAssignment.logistical_status.is_(None))
                    | (
                        DeliveryOrderAssignment.logistical_status
                        != LogisticalStatus.COMPLETED
                    )
                )

            total = query.count()
            rows = (
                query.options(
                    joinedload(DeliveryOrderAssignment.order).joinedload(
                        Order.shipping_address
                    ),
                    joinedload(DeliveryOrderAssignment.order)
                    .joinedload(Order.items)
                    .joinedload(OrderItem.seller),
                )
                .order_by(DeliveryOrderAssignment.assigned_at.desc())
                .offset((max(page, 1) - 1) * per_page)
                .limit(per_page)
                .all()
            )

            jobs = []
            for assignment in rows:
                order = assignment.order
                seller = None
                if order is not None:
                    seller = next(
                        (
                            item.seller
                            for item in order.items
                            if item.seller is not None
                        ),
                        None,
                    )
                jobs.append(
                    {
                        "assignment_id": assignment.assignment_id,
                        "order_id": assignment.order_id,
                        "order_number": getattr(order, "order_number", None),
                        "assigned_at": assignment.assigned_at,
                        "logistical_status": (
                            assignment.logistical_status.value
                            if assignment.logistical_status
                            else None
                        ),
                        "seller_name": (
                            getattr(seller, "shop_name", None) if seller else None
                        ),
                        "seller_image": DeliveryService._shop_image(seller),
                        # Read straight off the shipping address. This
                        # called _assignment_parties for one field of
                        # the dict it builds, and that walks the seller
                        # and the buyer through to their User rows --
                        # four extra queries per row of a paginated
                        # list, for two phone numbers nothing here shows.
                        "dropoff_address": DeliveryService._dropoff_line(order),
                        # What this job paid. Read from the order's own
                        # shipping fee through the same function the
                        # payout uses, so the history cannot quietly
                        # disagree with the wallet.
                        "earnings": (
                            earning_for_drop(order.shipping_fee, stops=1)
                            if order is not None
                            else None
                        ),
                    }
                )

            return {
                "jobs": jobs,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_items": total,
                    "total_pages": (total + per_page - 1) // per_page,
                },
            }

    @staticmethod
    def _dropoff_line(order) -> Optional[str]:
        """Where it is going, as one line."""
        drop = getattr(order, "shipping_address", None) if order else None
        if drop is None:
            return None
        return (
            ", ".join(
                str(part)
                for part in (
                    getattr(drop, "street_address", None),
                    getattr(drop, "city", None),
                )
                if part
            )
            or None
        )

    @staticmethod
    def _shop_address_line(seller) -> Optional[str]:
        """Seller.shop_address is a JSON blob; a rider needs one line."""
        shop_address = getattr(seller, "shop_address", None) if seller else None
        if not isinstance(shop_address, dict):
            return shop_address or None

        return (
            ", ".join(
                str(part)
                for part in (
                    shop_address.get("street"),
                    shop_address.get("street_address"),
                    shop_address.get("city"),
                )
                if part
            )
            or None
        )

    @staticmethod
    def _shop_image(seller) -> Optional[str]:
        """The shop's picture, for a rider looking for the right stall.

        User.profile_picture is the shop's avatar and banner_url the wide
        cover; the avatar is what a rider wants, since it is what the shop
        looks like rather than what its page looks like. "default.jpg" is
        the column default for a seller who never set one, and is a
        filename rather than a URL -- sending it gives the app a broken
        image to render, which is worse than sending nothing.
        """
        if not seller:
            return None

        avatar = getattr(getattr(seller, "user", None), "profile_picture", None)
        if avatar and avatar != "default.jpg":
            return avatar

        return getattr(seller, "banner_url", None) or None

    @staticmethod
    def _assignment_parties(order: Order) -> Dict:
        """The people at each end of a single-order delivery.

        Phone numbers are included because a rider standing outside a shut
        shop, or at a gate with no answer, has no other move -- every
        delivery app in the world puts a call button on that screen. They
        are the real numbers: masking them through a proxy is the right
        end state and needs a telephony provider we do not have yet.
        """
        seller = next(
            (item.seller for item in order.items if item.seller is not None), None
        )
        buyer_user = getattr(getattr(order, "buyer", None), "user", None)

        shop_address = DeliveryService._shop_address_line(seller)

        drop_line = DeliveryService._dropoff_line(order)

        return {
            "seller_name": getattr(seller, "shop_name", None) if seller else None,
            "seller_image": DeliveryService._shop_image(seller),
            "pickup_address": shop_address,
            "seller_phone": (
                getattr(getattr(seller, "user", None), "phone_number", None)
                if seller
                else None
            ),
            "buyer_name": getattr(buyer_user, "username", None),
            "dropoff_address": drop_line,
            "buyer_phone": getattr(buyer_user, "phone_number", None),
            "order_number": order.order_number,
            "parcel": DeliveryService._parcel_manifest(order),
        }

    @staticmethod
    def get_assignment_pickups_from_order_item(order: Order) -> List[Dict[str, float]]:
        # The shop's own coordinates, falling back to the seller's personal
        # address. This resolved from seller.user.address alone, which is
        # frequently unset -- so the pickup list came back empty and the
        # active-delivery map had no pickup pin at all. Same fix as
        # get_available_orders (riders could not see paid orders).
        pickups = []
        for item in order.items:
            seller = item.seller
            if not seller:
                continue

            lat = getattr(seller, "shop_latitude", None)
            lng = getattr(seller, "shop_longitude", None)
            if lat is None or lng is None:
                seller_address = getattr(getattr(seller, "user", None), "address", None)
                lat = getattr(seller_address, "latitude", None)
                lng = getattr(seller_address, "longitude", None)

            if lat is None or lng is None:
                continue
            pickups.append({"lat": lat, "lng": lng})
        return pickups

    @staticmethod
    def is_valid_status_transition(
        current_status: Optional[LogisticalStatus], new_status: LogisticalStatus
    ) -> bool:
        """
        Validates if a status transition is allowed.

        Status must follow this sequence:
        None -> ARRIVED_PICKUP -> PICKED_UP -> EN_ROUTE_TO_DROPOFF -> DELIVERED_PENDING_QR -> COMPLETED

        Args:
            current_status: The current LogisticalStatus (can be None for initial assignment)
            new_status: The desired LogisticalStatus

        Returns:
            bool: True if transition is valid, False otherwise
        """
        return new_status in DeliveryService.VALID_STATUS_TRANSITIONS.get(
            current_status, []
        )

    @staticmethod
    def update_assignment_status(
        user_id: str, assignment_id: str, new_status: str
    ) -> Dict:
        with session_scope() as session:
            assignment = (
                session.query(DeliveryOrderAssignment)
                .filter_by(assignment_id=assignment_id, delivery_user_id=user_id)
                .first()
            )
            if not assignment:
                logger.warning(
                    f"No active assignment found with ID {assignment_id} for user {user_id}"
                )
                raise NotFoundError("Active assignment not found")

            # Parse new_status string to LogisticalStatus Enum
            try:
                logistical_status = LogisticalStatus[new_status.upper()]
            except KeyError:
                logger.warning(
                    f"Invalid status value: {new_status} is not a valid LogisticalStatus for assignment {assignment_id}"
                )
                raise ValidationError("Invalid status value")

            # Validate status transition
            current_status = assignment.logistical_status
            if not DeliveryService.is_valid_status_transition(
                current_status, logistical_status
            ):
                valid_transitions = DeliveryService.VALID_STATUS_TRANSITIONS.get(
                    current_status, []
                )
                valid_status_names = (
                    [s.value for s in valid_transitions] if valid_transitions else []
                )
                logger.warning(
                    f"Invalid status transition from {current_status.value if current_status else 'None'} to {logistical_status.value} for assignment {assignment_id}. Valid next statuses: {valid_status_names}"
                )
                raise ValidationError(
                    f"Cannot transition from {current_status.value if current_status else 'unassigned'} to {logistical_status.value}. Valid statuses: {', '.join(valid_status_names) if valid_status_names else 'None'}"
                )

            assignment.logistical_status = logistical_status

            # Pickup is the item-level equivalent of "shipped" for orders
            # fulfilled through Markt's own delivery network -- keep OrderItem
            # in step so a rider-managed order reaches DELIVERED through the
            # same validated SHIPPED->DELIVERED transition as a seller-managed
            # one, instead of needing a special case at POD time.
            if logistical_status == LogisticalStatus.PICKED_UP:
                order = session.query(Order).filter_by(id=assignment.order_id).first()
                if order:
                    for item in order.items:
                        if item.status == OrderItem.Status.PROCESSING:
                            item.transition_to(OrderItem.Status.SHIPPED)

            advance_buyer_delivery(
                session,
                assignment.order_id,
                DeliveryService._BUYER_DELIVERY_STATE.get(logistical_status),
            )

            # Who to tell, gathered while the session is still open.
            # NotificationService.create_notification opens its own
            # session_scope, so firing from in here would nest one
            # transaction inside another -- failure.py has the same shape
            # and the same comment.
            audience = DeliveryService._delivery_audience(session, assignment)

            session.commit()

        DeliveryService._notify_delivery_progress(audience, logistical_status)

        return {"status": logistical_status.value}

    # Who hears about a rider reaching each step, and what they are told.
    #
    # The buyer hears about all of it: it is their parcel, and before this
    # their order went silent the moment they paid for it. The seller hears
    # only the two steps that ask something of them -- someone is coming,
    # and someone is outside -- because a shop does not need to know the
    # rider has set off for a buyer across town.
    #
    # COMPLETED is absent deliberately: the POD confirm path already tells
    # both sides the order was delivered, and a second "delivered" a moment
    # later reads as a duplicate.
    _BUYER_PROGRESS = {
        LogisticalStatus.ARRIVED_PICKUP: "{rider} has reached the shop to collect order {order}.",
        LogisticalStatus.PICKED_UP: "{rider} has collected order {order}.",
        LogisticalStatus.EN_ROUTE_TO_DROPOFF: "{rider} is on the way with order {order}.",
        LogisticalStatus.DELIVERED_PENDING_QR: (
            "{rider} has arrived with order {order}. Have your delivery code ready."
        ),
    }

    _SELLER_PROGRESS = {
        LogisticalStatus.ARRIVED_PICKUP: "{rider} is at your shop to collect order {order}.",
        LogisticalStatus.PICKED_UP: "{rider} has collected order {order} from your shop.",
    }

    # What the buyer's tracker should read at each step the rider reports.
    #
    # Coarser than LogisticalStatus on purpose: OrderDelivery.state is the
    # buyer's view of their own parcel, and "the rider is standing in the
    # shop" is not a state a buyer tracks. ARRIVED_PICKUP and
    # DELIVERED_PENDING_QR are therefore absent -- the first is still
    # ASSIGNED, and the second is still IN_TRANSIT, because a parcel at the
    # door with the code not yet confirmed has not been delivered.
    _BUYER_DELIVERY_STATE = {
        LogisticalStatus.PICKED_UP: DeliveryState.PICKED_UP,
        LogisticalStatus.EN_ROUTE_TO_DROPOFF: DeliveryState.IN_TRANSIT,
        LogisticalStatus.COMPLETED: DeliveryState.DELIVERED,
    }

    @staticmethod
    def _delivery_audience(session, assignment) -> Dict:
        """The people behind one assignment, as plain values.

        Plain values rather than model objects on purpose: these outlive
        the session they were read in, and a lazy load after it closes is
        a DetachedInstanceError inside an `except Exception` that nobody
        would ever see.

        Every read is defensive, and the whole thing is wrapped: this runs
        inside the transaction that just moved a real delivery forward, and
        failing to work out who to tell must not undo the step the rider
        already took. An empty dict means nobody gets told, which is
        exactly the behaviour this replaces.
        """
        try:
            order = session.query(Order).filter_by(id=assignment.order_id).first()
            if not order:
                return {}

            buyer_user = getattr(getattr(order, "buyer", None), "user", None)

            seller_user_ids = []
            for item in getattr(order, "items", None) or []:
                seller_user_id = getattr(getattr(item, "seller", None), "user_id", None)
                if seller_user_id and seller_user_id not in seller_user_ids:
                    seller_user_ids.append(seller_user_id)

            rider = getattr(assignment, "delivery_user", None)

            return {
                "order_id": getattr(order, "id", None),
                "order_number": getattr(order, "order_number", None),
                "buyer_user_id": getattr(buyer_user, "id", None),
                "seller_user_ids": seller_user_ids,
                "rider_name": getattr(rider, "name", None) or "Your rider",
            }
        except Exception:
            logger.exception(
                "Could not work out who to notify about assignment %s",
                getattr(assignment, "assignment_id", None),
            )
            return {}

    @staticmethod
    def _notify_delivery_progress(
        audience: Dict, logistical_status: LogisticalStatus
    ) -> None:
        DeliveryService._send_delivery_notice(
            audience,
            buyer_text=DeliveryService._BUYER_PROGRESS.get(logistical_status),
            seller_text=DeliveryService._SELLER_PROGRESS.get(logistical_status),
            status_value=logistical_status.value,
        )

    @staticmethod
    def _send_delivery_notice(
        audience: Dict,
        buyer_text: Optional[str],
        seller_text: Optional[str],
        status_value: str,
    ) -> None:
        if not audience:
            return

        label = audience.get("order_number") or audience.get("order_id") or ""
        rider_name = audience.get("rider_name") or "Your rider"

        def send(user_id, notification_type, text):
            if not user_id or not text:
                return
            try:
                NotificationService.create_notification(
                    user_id=user_id,
                    notification_type=notification_type,
                    reference_type="order",
                    reference_id=audience.get("order_id"),
                    metadata_={
                        "message": text.format(rider=rider_name, order=label),
                        "order_number": audience.get("order_number"),
                        "logistical_status": status_value,
                    },
                )
            except Exception:
                # A delivery must not fail because a notification did. The
                # rider has already moved; the step is already committed.
                logger.exception(
                    "Could not notify %s of %s on order %s",
                    user_id,
                    status_value,
                    audience.get("order_id"),
                )

        send(
            audience.get("buyer_user_id"),
            NotificationType.DELIVERY_STATUS_UPDATE,
            buyer_text,
        )

        for seller_user_id in audience.get("seller_user_ids", []):
            send(
                seller_user_id,
                NotificationType.DELIVERY_PICKUP_UPDATE,
                seller_text,
            )

    @staticmethod
    def get_buyer_pod_code(order_id: str, user_id: str) -> Dict:
        """10.6 POD handshake, buyer side: the buyer's app displays this
        code so the rider can read/enter it back at the door -- both
        existing rider-side confirm calls (confirm_order_qr_code below,
        and DeliveryRunPodService.confirm_order_pod) already just take a
        `qr_code` string with no assumption about how the rider learned
        it, so neither needed any change for this. Before this, the only
        way to fetch either code was the rider-authenticated GET
        endpoints (get_order_qr_code below, DeliveryRunPodService.
        get_order_pod_qr) -- meaning a rider could always fetch and
        immediately submit their own code back with no buyer step at all,
        which isn't real proof of anything. This is what closes that gap.

        Checks both delivery systems, since an order can be served by
        either today (10's own note: single-order is what actually works
        end-to-end right now; the batched DeliveryRun model is the real
        target direction, not yet fully rider-driven) -- single-order
        first, then the run-based join table. Same ownership-check
        convention as OrderService.track_order (user_id is the buyer's
        own User.id, not their Buyer account id).
        """
        with session_scope() as session:
            order = session.query(Order).options(joinedload(Order.buyer)).get(order_id)
            if not order:
                raise NotFoundError("Order not found")
            if not order.buyer or order.buyer.user_id != user_id:
                raise ForbiddenError("You can only view your own order's delivery code")

            assignment = (
                session.query(DeliveryOrderAssignment)
                .filter_by(order_id=order_id, status=AssignmentStatus.ACCEPTED)
                .order_by(DeliveryOrderAssignment.assigned_at.desc())
                .first()
            )
            # A code that has already been used is not a code any more.
            #
            # This returned the escrow code for as long as the assignment
            # existed, which is forever -- so after the rider had scanned
            # it and gone, the buyer's app still offered "View my delivery
            # code" and still drew a live QR for a delivery that was over.
            # Nothing was listening for that code any more, and showing a
            # spent one invites somebody to try it.
            if (
                assignment
                and assignment.logistical_status == LogisticalStatus.COMPLETED
            ):
                return {
                    "ready": False,
                    "system": "single_order",
                    "code": None,
                    "delivered": True,
                }

            if assignment and assignment.escrow_qr_code:
                return {
                    "ready": True,
                    "system": "single_order",
                    "code": assignment.escrow_qr_code,
                    "delivered": False,
                }

            from .models import DeliveryRunOrder, DeliveryRunOrderPodStatus

            run_order = (
                session.query(DeliveryRunOrder).filter_by(order_id=order_id).first()
            )
            if run_order and run_order.pod_status == (
                DeliveryRunOrderPodStatus.DELIVERED
            ):
                return {
                    "ready": False,
                    "system": "run",
                    "code": None,
                    "delivered": True,
                }

            if (
                run_order
                and run_order.pod_status == DeliveryRunOrderPodStatus.QR_ISSUED
            ):
                return {
                    "ready": True,
                    "system": "run",
                    "code": run_order.qr_code,
                    "delivered": False,
                }

            # Not ready and not delivered: no rider yet, or a rider who
            # has not finished collecting. The buyer is waiting, which is
            # a different thing from being finished.
            return {
                "ready": False,
                "system": None,
                "code": None,
                "delivered": False,
            }

    @staticmethod
    def get_order_qr_code(user_id: str, order_id: str) -> Dict:
        with session_scope() as session:
            assignment = (
                session.query(DeliveryOrderAssignment)
                .filter_by(
                    order_id=order_id,
                    delivery_user_id=user_id,
                    status=AssignmentStatus.ACCEPTED,
                )
                .first()
            )
            if not assignment:
                logger.warning(
                    f"No accepted assignment found for order {order_id} and user {user_id}"
                )
                raise NotFoundError("Accepted assignment not found")

            return {
                "qr_code": assignment.escrow_qr_code or "",
                "order_id": order_id,
            }

    @staticmethod
    def confirm_order_qr_code(user_id: str, order_id: str, qr_code: str) -> Dict:
        with session_scope() as session:
            # query the assignment to get the escrow QR code
            assignment = (
                session.query(DeliveryOrderAssignment)
                .filter_by(
                    order_id=order_id,
                    delivery_user_id=user_id,
                    status=AssignmentStatus.ACCEPTED,
                )
                .first()
            )
            if not assignment:
                logger.warning(
                    f"No accepted assignment found for order {order_id} and user {user_id}"
                )
                raise NotFoundError("Accepted assignment not found")

            if not assignment.escrow_qr_code or assignment.escrow_qr_code != qr_code:
                logger.warning(
                    f"Invalid QR code provided for order {order_id} by user {user_id}"
                )
                raise ValidationError("Invalid QR code")

            order = session.query(Order).filter_by(id=order_id).first()
            if not order:
                logger.warning(f"No order found with ID {order_id}")
                raise NotFoundError("Order not found")

            if not DeliveryService.is_valid_status_transition(
                assignment.logistical_status, LogisticalStatus.COMPLETED
            ):
                logger.warning(
                    f"QR confirm attempted for order {order_id} while assignment "
                    f"is at {assignment.logistical_status}, not DELIVERED_PENDING_QR"
                )
                raise ValidationError(
                    "Delivery is not ready for proof-of-delivery confirmation"
                )

            # POD starts the settlement hold (Phase 0: 12h) for every
            # item's seller, not just items a seller separately marked
            # shipped/delivered themselves. Cancelled items are skipped
            # entirely -- never transitioned, never paid. Settlement itself
            # happens later, via WalletService.settle_eligible_order_items
            # once the hold elapses -- POD no longer pays out immediately.
            for item in order.items:
                if item.status == OrderItem.Status.CANCELLED:
                    continue
                if item.status != OrderItem.Status.DELIVERED:
                    item.transition_to(OrderItem.Status.DELIVERED)
                    OrderEventService.emit(
                        session,
                        order_id=order.id,
                        order_item_id=item.id,
                        event_type=OrderEventType.ITEM_DELIVERED,
                        actor_type=ActorType.RIDER,
                        actor_id=user_id,
                    )
                if item.delivered_at is None:
                    item.delivered_at = datetime.utcnow()

            assignment.logistical_status = LogisticalStatus.COMPLETED
            # The buyer's own tracker, which this path never touched --
            # the last thing it said was "Rider requested".
            advance_buyer_delivery(session, order.id, DeliveryState.DELIVERED)
            rider_id = assignment.delivery_user_id
            reference_id = assignment.assignment_id
            # One stop: the whole shipping fee is this trip's revenue.
            # The rider takes a share of it rather than all of it -- see
            # app/deliveries/rider_pay.py for why both payout paths now go
            # through one function.
            earning_amount = earning_for_drop(order.shipping_fee, stops=1)
            session.commit()

        # Delegate order-level completion (status, realtime event, gamification)
        # to the single source of truth so the QR path gets the same side effects
        # as every other way an order can be marked delivered.
        OrderService.update_order_status(order_id, OrderStatus.DELIVERED)

        # Outside the transaction above -- WalletService.credit opens its own
        # session_scope(), and a wallet bug must never roll back a delivery
        # that has already genuinely happened. Logged, not raised: the rider
        # did the work either way, and a crediting failure here needs someone
        # to notice and backfill, not a 500 on the buyer-facing POD flow.
        if earning_amount and earning_amount > 0:
            try:
                WalletService.credit_delivery_earning(
                    rider_id, earning_amount, reference_id
                )
            except Exception:
                logger.exception(
                    "Failed to credit rider %s for delivery %s", rider_id, reference_id
                )

        return {"status": "success", "message": "Order marked as delivered"}

    @staticmethod
    def find_delivery_order_buyer(user_id: str, room_id: str) -> bool:
        """Checks if the user passed is one of the buyers in a delivery order associated with the room.

        user_id is the marketplace User.id (from the buyer's session). We resolve via Buyer
        since Order.buyer_id references buyers.id, not users.id.
        """
        with session_scope() as session:
            # First, get the location room and its associated assignments
            location_room = (
                session.query(LocationUpdateRoom).filter_by(room_id=room_id).first()
            )
            if not location_room:
                logger.warning(f"Room {room_id} not found")
                return False

            # Explicit column: room_id is on OrderLocationMapping, not Order. Join Buyer to match
            # by User.id (socket sends buyer's User.id).
            mapping = (
                session.query(OrderLocationMapping)
                .join(Order, OrderLocationMapping.order_id == Order.id)
                .join(Buyer, Order.buyer_id == Buyer.id)
                .filter(OrderLocationMapping.room_id == room_id)
                .filter(Buyer.user_id == user_id)
                .first()
            )
            if not mapping:
                logger.warning(f"User {user_id} is not authorized for room {room_id}")
                return False

            return True

    @staticmethod
    def is_delivery_partner_for_room(delivery_user_id: str, room_id: str) -> bool:
        """True if this delivery partner is assigned to the given location room (e.g. can send location updates)."""
        with session_scope() as session:
            room = (
                session.query(LocationUpdateRoom)
                .filter_by(room_id=room_id, delivery_user_id=delivery_user_id)
                .first()
            )
            if room:
                return True
            # Also allow if they have an accepted assignment linked to this room
            assignment = (
                session.query(DeliveryOrderAssignment)
                .filter_by(
                    delivery_user_id=delivery_user_id,
                    room_id=room_id,
                    status=AssignmentStatus.ACCEPTED,
                )
                .first()
            )
            return assignment is not None
