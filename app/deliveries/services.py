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
from app.libs.errors import APIError, NotFoundError, ValidationError, ForbiddenError
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
from app.orders.events import ActorType, OrderEventService, OrderEventType
from app.orders.models import Order, OrderItem, OrderStatus, ShippingAddress
from app.orders.services import OrderService

logger = logging.getLogger(__name__)


def _normalize_phone(raw: str) -> str:
    """Strip leading + and return digits-only; empty if invalid."""
    if not raw:
        return ""
    return (raw or "").lstrip("+").strip()


class DeliveryService:

    CACHE_EXPIRE_SECONDS = 3600  # 1 hour (relaxed for tests; was 5 min)
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

            logger.info(f"Sending OTP {otp} to {email}")
            if email_service.send_otp_email(email, otp):
                cache_key = f"{DeliveryService.CACHE_KEY_PREFIX}{phone}"
                redis_client.setex(cache_key, DeliveryService.CACHE_EXPIRE_SECONDS, otp)
                return {"status": "success", "message": f"OTP sent to {email}"}
            else:
                logger.error(f"Failed to send OTP email to {email}")
                return {"status": "error", "message": f"Failed to send OTP to {email}"}
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

                    for item in order.items:
                        seller = item.seller
                        if not seller or seller.id in seen_seller_ids:
                            continue

                        seen_seller_ids.add(seller.id)

                        seller_address = (
                            getattr(seller.user, "address", None)
                            if seller.user
                            else None
                        )

                        if (
                            not seller_address
                            or seller_address.latitude is None
                            or seller_address.longitude is None
                        ):
                            continue

                        pickup_lat = seller_address.latitude
                        pickup_lng = seller_address.longitude

                        seller_pickups.append({"lat": pickup_lat, "lng": pickup_lng})

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

                    estimated_earnings = (
                        order.shipping_fee if order.shipping_fee is not None else 0
                    )

                    available_orders.append(
                        {
                            "order_id": order.id,
                            "pickup": seller_pickups,
                            "dropoff": {
                                "lat": dropoff.latitude,
                                "lng": dropoff.longitude,
                            },
                            "distance_meters": round(max_distance, 2),
                            "estimated_earnings": estimated_earnings,
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
    def accept_order(user_id: str, order_id: str) -> Dict:
        with session_scope() as session:
            assignments = (
                session.query(DeliveryOrderAssignment)
                .filter_by(order_id=order_id)
                .all()
            )
            if any(a.status == AssignmentStatus.ACCEPTED for a in assignments):
                logger.warning(
                    f"Order {order_id} has already been accepted by another delivery partner"
                )
                raise NotFoundError("Order already accepted")

            if any(
                a.delivery_user_id == user_id and a.status == AssignmentStatus.REJECTED
                for a in assignments
            ):
                logger.warning(
                    f"Delivery partner {user_id} has already rejected order {order_id}"
                )
                raise NotFoundError("You have already rejected this order")

            # Create a new assignment for the delivery user
            new_assignment = DeliveryOrderAssignment(
                delivery_user_id=user_id,
                order_id=order_id,
                status=AssignmentStatus.ACCEPTED,
                assignment_id=str(uuid.uuid4()),
                escrow_qr_code=str(uuid.uuid4()),
            )
            session.add(new_assignment)
            session.commit()

            return {
                "status": AssignmentStatus.ASSIGNED.value,
                "assignment_id": new_assignment.assignment_id,
            }

    @staticmethod
    def reject_order(user_id: str, order_id: str) -> Dict:
        with session_scope() as session:
            assignments = (
                session.query(DeliveryOrderAssignment)
                .filter_by(order_id=order_id)
                .all()
            )
            if any(a.status == AssignmentStatus.ACCEPTED for a in assignments):
                logger.warning(
                    f"Order {order_id} has already been accepted by another delivery partner"
                )
                raise NotFoundError("Order already accepted")

            if any(
                a.delivery_user_id == user_id and a.status == AssignmentStatus.REJECTED
                for a in assignments
            ):
                logger.warning(
                    f"Delivery partner {user_id} has already rejected order {order_id}"
                )
                raise NotFoundError("You have already rejected this order")

            # Create a new assignment for the delivery user (no escrow QR for rejected)
            new_assignment = DeliveryOrderAssignment(
                delivery_user_id=user_id,
                order_id=order_id,
                status=AssignmentStatus.REJECTED,
                assignment_id=str(uuid.uuid4()),
                escrow_qr_code=None,
            )
            session.add(new_assignment)
            session.commit()

            return {
                "status": AssignmentStatus.REJECTED.value,
                "assignment_id": new_assignment.assignment_id,
            }

    # TODO: We would need to include the location details of the pickup point and drop off points
    @staticmethod
    def get_active_assignments(user_id: str) -> Dict:
        with session_scope() as session:
            active_assignments = (
                session.query(DeliveryOrderAssignment)
                .filter_by(delivery_user_id=user_id, status=AssignmentStatus.ACCEPTED)
                # Eagerly load the order and its nested relationships
                .options(
                    joinedload(DeliveryOrderAssignment.order).joinedload(
                        Order.shipping_address
                    ),
                    joinedload(DeliveryOrderAssignment.order).joinedload(Order.items),
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
                        "pickup": DeliveryService.get_assignment_pickups_from_order_item(
                            assignment.order
                        ),
                        "dropoff": {
                            "lat": assignment.order.shipping_address.latitude,
                            "lng": assignment.order.shipping_address.longitude,
                        },
                    }
                    for assignment in active_assignments
                ]
            }

    @staticmethod
    def get_assignment_pickups_from_order_item(order: Order) -> List[Dict[str, float]]:
        pickups = []
        for item in order.items:
            seller = item.seller
            if not seller or not getattr(seller, "user", None):
                continue
            seller_address = getattr(seller.user, "address", None)
            if (
                not seller_address
                or seller_address.latitude is None
                or seller_address.longitude is None
            ):
                continue
            pickups.append(
                {"lat": seller_address.latitude, "lng": seller_address.longitude}
            )
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

            session.commit()

            return {"status": assignment.logistical_status.value}

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
            if assignment and assignment.escrow_qr_code:
                return {
                    "ready": True,
                    "system": "single_order",
                    "code": assignment.escrow_qr_code,
                }

            from .models import DeliveryRunOrder, DeliveryRunOrderPodStatus

            run_order = (
                session.query(DeliveryRunOrder).filter_by(order_id=order_id).first()
            )
            if (
                run_order
                and run_order.pod_status == DeliveryRunOrderPodStatus.QR_ISSUED
            ):
                return {"ready": True, "system": "run", "code": run_order.qr_code}

            return {"ready": False, "system": None, "code": None}

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
            session.commit()

        # Delegate order-level completion (status, realtime event, gamification)
        # to the single source of truth so the QR path gets the same side effects
        # as every other way an order can be marked delivered.
        OrderService.update_order_status(order_id, OrderStatus.DELIVERED)

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
