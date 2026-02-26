# python imports
import logging
import uuid
import math
from random import randint
from typing import Optional, Dict, Any, List
from enum import Enum

# flask imports
from flask_login import current_user, login_user

# package imports
from app.users.models import User, Seller, UserAddress
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from sqlalchemy.orm import joinedload

# project imports
from external.redis import redis_client
from app.libs.session import session_scope
from app.libs.pagination import Paginator
from app.libs.errors import NotFoundError, ValidationError
from app.libs.email_service import email_service

# app imports
from .models import (
    DeliveryUser, DeliveryLastLocation, DeliveryOrderAssignment, 
    DeliveryStatus, DeliveryVehicleType, AssignmentStatus, LogisticalStatus,
    LocationUpdateRoom, OrderLocationMapping
)
from app.orders.models import Order, OrderItem, OrderStatus, ShippingAddress
from app.orders.services import OrderService

logger = logging.getLogger(__name__)


class DeliveryService:

    CACHE_EXPIRE_SECONDS = 300  # Cache OTP for 5 minutes
    CACHE_KEY_PREFIX = "otp_cache:"

    @staticmethod
    def login_delivery_partner(phone_number: str, otp: str) -> Dict:
        """Authenticate delivery partner and return partner details"""

        """ Validate that the phone number exists, and it is in the correct format. """
        if not phone_number or not phone_number.isdigit() or len(phone_number) <= 10:
            logger.warning(f"Invalid phone number format: {phone_number}")
            raise NotFoundError("Invalid phone number format")
        try:
            # Validate OTP from cache
            cache_key = f"{DeliveryService.CACHE_KEY_PREFIX}{phone_number}"
            cached_otp = redis_client.get(cache_key)
            if not cached_otp or cached_otp.decode() != otp:
                logger.warning(f"Invalid OTP for phone number {phone_number}")
                raise NotFoundError("Invalid OTP")

            # OTP is valid, fetch delivery partner details
            with session_scope() as session:
                delivery_user = session.query(DeliveryUser).filter_by(phone_number=phone_number).first()
                if not delivery_user:
                    logger.warning(f"No delivery partner found with phone number {phone_number}")
                    raise NotFoundError("Delivery partner not found")
                
                # attempt to login the user here 
                login_user(delivery_user)
                return {
                    "partner": {
                        "id": delivery_user.id,
                        "name": delivery_user.name,
                        "status": delivery_user.status.value,
                    }
                }
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            raise NotFoundError("Login failed")

    @staticmethod
    def send_otp(phone_number: str) -> bool:
        """Generate and send OTP to delivery partner's email (phone number would be used later when we integrate SMS service)"""
        try:
            # Generate a random 6-digit OTP
            otp = f"{randint(100000, 999999)}"

            #attempt to get delivery partner's email from database using phone number
            with session_scope() as session:
                delivery_user = session.query(DeliveryUser).filter_by(phone_number=phone_number).first()
                if not delivery_user:
                    logger.warning(f"No delivery partner found with phone number {phone_number}")
                    raise NotFoundError("Delivery partner not found")

                email = delivery_user.email
                if not email:
                    logger.warning(f"No email found for delivery partner with phone number {phone_number}")
                    raise NotFoundError("Email not found")
            cache_key = f"{DeliveryService.CACHE_KEY_PREFIX}{phone_number}"
            redis_client.setex(cache_key, DeliveryService.CACHE_EXPIRE_SECONDS, otp)

            #future versions would be made to send through phone number using an SMS service
            logger.info(f"Sending OTP {otp} to {email}")
            email_service.send_otp_email(email, otp)
            return {"status": "success", "message": f"OTP sent to {email}"}
        except Exception as e:
            logger.error(f"Error sending OTP: {str(e)}")
            return {"status": "error", "message": "Failed to send OTP", "error": str(e)}
        
    @staticmethod
    def register_delivery_partner(data: Dict) -> Dict:
        """Register a new delivery partner"""
        try:
            #validate the input data
            if not data.get("phone_number") or not data["phone_number"].isdigit() or len(data["phone_number"]) <= 10:
                logger.warning(f"Invalid phone number format: {data.get('phone_number')}")
                raise ValidationError("Invalid phone number format")
            
            if not data.get("email") or "@" not in data["email"]:
                logger.warning(f"Invalid email format: {data.get('email')}")
                raise ValidationError("Invalid email format")
            
            if not data.get("name"):
                logger.warning("Name is required for registration")
                raise ValidationError("Name is required")

            with session_scope() as session:
                new_partner = DeliveryUser(
                    phone_number=data["phone_number"],
                    email=data.get("email"),
                    name=data["name"],
                    status=DeliveryStatus.INACTIVE,  # New partners start as INACTIVE until they complete onboarding
                    vehicle_type=DeliveryVehicleType[data.get("vehicle_type").upper()] if data.get("vehicle_type") and data.get("vehicle_type").upper() in [e.name for e in DeliveryVehicleType] else DeliveryVehicleType.BIKE
                )
                session.add(new_partner)
                session.commit()

                return {
                    "id": new_partner.id,
                    "name": new_partner.name,
                    "status": new_partner.status.value,
                    "vehicleType": new_partner.vehicle_type.value if new_partner.vehicle_type else None,
                }
        except Exception as e:
            logger.error(f"Error registering delivery partner: {str(e)}")
            # we need to check that the error is not due to duplicate phone number or email
            if "duplicate key value violates unique constraint" in str(e):
                if "phone_number" in str(e):
                    logger.warning(f"Phone number {data.get('phone_number')} already exists")
                    raise ValidationError("Phone number already registered")
                elif "email" in str(e):
                    logger.warning(f"Email {data.get('email')} already exists")
                    raise ValidationError("Email already registered")
            raise ValidationError(f"Failed to register delivery partner")


    @staticmethod
    def get_current_delivery_partner(user_id: str) -> Dict:
        """Get current delivery partner details"""
        try:
            with session_scope() as session:
                delivery_user = session.query(DeliveryUser).filter_by(user_id=user_id).first()
                if not delivery_user:
                    logger.warning(f"No delivery partner found for user ID {user_id}")
                    raise NotFoundError("Delivery partner not found")

                return {
                    
                    "id": delivery_user.id,
                    "name": delivery_user.name,
                    "status": delivery_user.status.value,
                    "vehicleType": delivery_user.vehicle_type.value if delivery_user.vehicle_type else None,
                    "rating": delivery_user.rating,
                }
        except Exception as e:
            logger.error(f"Error fetching current delivery partner: {str(e)}")
            raise NotFoundError("Failed to fetch delivery partner")
        
    @staticmethod
    def update_delivery_partner_status(user_id: str) -> Dict:
        """Update current delivery partner status"""
        try:
            with session_scope() as session:
                delivery_user = session.query(DeliveryUser).filter_by(user_id=user_id).first()
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
    def update_delivery_partner_location(user_id: str, location: Dict[str, float]) -> Dict:
        """Update delivery partner location"""
        try:
            with session_scope() as session:
                delivery_user = session.query(DeliveryUser).filter_by(user_id=user_id).first()
                if not delivery_user:
                    logger.warning(f"No delivery partner found for user ID {user_id}")
                    raise NotFoundError("Delivery partner not found")

                # Update the delivery user's last known location
                delivery_user.last_location = DeliveryLastLocation(
                    delivery_user_id=delivery_user.id,
                    latitude=location["lat"],
                    longitude=location["lng"],
                    accuracy=location.get("accuracy"),
                    speed=location.get("speed"),
                )

                session.add(delivery_user)
                session.commit()

                # In a real implementation, we would also broadcast this location update to any relevant clients (e.g. via WebSocket)
        except Exception as e:
            logger.error(f"Error updating delivery partner location: {str(e)}")
            raise NotFoundError("Failed to update location")
        return {"status": "success", "message": "Location updated"}
    
    #slightly complex functionality
    #we would need, after the MVP, to optimize this
    #either by using postGIS to calculate the distance properly,
    #or by pre-calculating the distance between the delivery partner and the sellers and caching that in Redis, and then just fetching the available orders based on the cached distances
    @staticmethod
    def get_available_orders(user_id: str, search_radius: int = 3000) -> Dict:
        """Get available orders for the delivery partner"""
        try:
            with session_scope() as session:

                delivery_user = (
                    session.query(DeliveryUser)
                    .filter(DeliveryUser.id == user_id)
                    .first()
                )

                if not delivery_user or not delivery_user.last_location:
                    raise NotFoundError("Delivery partner location not found")

                delivery_lat = delivery_user.last_location.latitude
                delivery_lng = delivery_user.last_location.longitude

                orders = (
                    session.query(Order)
                    .join(ShippingAddress, Order.id == ShippingAddress.order_id)
                    .join(OrderItem, Order.id == OrderItem.order_id)
                    .join(Seller, OrderItem.seller_id == Seller.id)
                    .join(User, Seller.user_id == User.id)
                    .join(UserAddress, User.id == UserAddress.user_id)
                    .filter(Order.status == OrderStatus.PROCESSING)
                    .options(
                        joinedload(Order.shipping_address),
                        joinedload(Order.items).joinedload(OrderItem.seller)
                    )
                    .distinct()
                    .all()
                )
                #Note: This is just a simplified way to find the orders within a radius, we would shift to using PostGIS for production later
                #We would need to paginate this result 

                available_orders = []

                for order in orders:

                    seller_pickups = []
                    total_distance = 0

                    dropoff = order.shipping_address

                    if not dropoff or dropoff.latitude is None:
                        continue

                    # Assuming first seller for MVP
                    #TODO: We would need to handle multiple sellers for an order later on, we can calculate the pickup location for each seller and return that in the response, for now we are just using the first seller's location as the pickup point
                    #order_tolerance_limit = 3 #meaning if some orders have ranges longer than the search radius, we can still include them
                    
                    for item in order.items:
                        seller = item.seller
                        seller_address = seller.user.address

                        if not seller_address:
                            continue

                        pickup_lat = seller_address.latitude
                        pickup_lng = seller_address.longitude

                        seller_pickups.append({
                            "lat": pickup_lat,
                            "lng": pickup_lng
                        })

                        distance = DeliveryService.haversine_distance(
                            delivery_lat,
                            delivery_lng,
                            pickup_lat,
                            pickup_lng
                        )

                        total_distance += distance
                    
                    average_distance = total_distance / len(order.items) if order.items else 0

                    if average_distance > search_radius:
                        continue

                    drop_lat = dropoff.latitude
                    drop_lng = dropoff.longitude

                    #Will need to calculate the estimated earnings based on the delivery fee for the order, for now I am just using the shipping fee as the estimated earnings, but we would need to have a more complex calculation later on based on the distance and other factors
                    estimated_earnings = order.shipping_fee or 0

                    available_orders.append({
                        "order_id": order.id,
                        "pickup": seller_pickups,
                        "dropoff": {
                            "lat": drop_lat,
                            "lng": drop_lng
                        },
                        "distance_meters": round(distance, 2),
                        "estimated_earnings": estimated_earnings
                    })

                return {
                    "range_meters": search_radius,
                    "orders": available_orders
                }
        except Exception as e:
            logger.error(f"Error fetching available orders: {str(e)}")
            raise NotFoundError("Failed to fetch available orders")
        
    @staticmethod
    def haversine_distance(lat1, lng1, lat2, lng2):
        R = 6371000  # Earth radius in meters

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lng2 - lng1)

        a = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1)
            * math.cos(phi2)
            * math.sin(delta_lambda / 2) ** 2
        )

        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c


    @staticmethod
    def accept_order(user_id: str, order_id: str) -> Dict:
        with session_scope() as session:
            assignments = session.query(DeliveryOrderAssignment).filter_by(order_id=order_id).all()
            if any(a.status == AssignmentStatus.ACCEPTED for a in assignments):
                logger.warning(f"Order {order_id} has already been accepted by another delivery partner")
                raise NotFoundError("Order already accepted")

            if any(a.delivery_user_id == user_id and a.status == AssignmentStatus.REJECTED for a in assignments):
                logger.warning(f"Delivery partner {user_id} has already rejected order {order_id}")
                raise NotFoundError("You have already rejected this order")

            # Create a new assignment for the delivery user
            new_assignment = DeliveryOrderAssignment(
                delivery_user_id=user_id,
                order_id=order_id,
                status=AssignmentStatus.ACCEPTED,
                assignment_id=str(uuid.uuid4()),
                escrow_qr_code=str(uuid.uuid4())
            )
            session.add(new_assignment)
            session.commit()

            return {"status": AssignmentStatus.ASSIGNED.value, "assignmentId": new_assignment.assignment_id}
        
    @staticmethod
    def reject_order(user_id: str, order_id: str) -> Dict:
        with session_scope() as session:
            assignments = session.query(DeliveryOrderAssignment).filter_by(order_id=order_id).all()
            if any(a.status == AssignmentStatus.ACCEPTED for a in assignments):
                logger.warning(f"Order {order_id} has already been accepted by another delivery partner")
                raise NotFoundError("Order already accepted")

            if any(a.delivery_user_id == user_id and a.status == AssignmentStatus.REJECTED for a in assignments):
                logger.warning(f"Delivery partner {user_id} has already rejected order {order_id}")
                raise NotFoundError("You have already rejected this order")

            # Create a new assignment for the delivery user
            new_assignment = DeliveryOrderAssignment(
                delivery_user_id=user_id,
                order_id=order_id,
                status=AssignmentStatus.REJECTED,
                assignment_id=str(uuid.uuid4())
            )
            session.add(new_assignment)
            session.commit()

            return {"status": AssignmentStatus.ASSIGNED.value, "assignmentId": new_assignment.assignment_id}
    
    #TODO: We would need to include the location details of the pickup point and drop off points
    @staticmethod
    def get_active_assignments(user_id: str) -> Dict:
        with session_scope() as session:
            active_assignments = (
                session.query(DeliveryOrderAssignment)
                .filter_by(delivery_user_id=user_id, status=AssignmentStatus.ACCEPTED)
                .all())
            #TODO: We would need to include the location details of the pickup point and drop off points, we can get that from the Order model using the order_id in the assignment
            #NOTE: pickup and dropoff location details are not included in the current implementation of the Order model, we would need to add that in order to return the required data for the active assignments endpoint
            return {
                "assignments": [
                    {
                        "assignmentId": assignment.assignment_id,
                        "orderId": assignment.order_id,
                        "assignedAt": assignment.assigned_at.isoformat(),
                        "status": assignment.status.value,
                        "pickup": [{
                            "lat": assignment_pickup.lat,
                            "lng": assignment_pickup.lng
                        } for assignment_pickup in DeliveryService.get_assignment_pickups_from_order_item(assignment.order)],
                        "dropoff": {
                            "lat": assignment.order.shipping_address.latitude,
                            "lng": assignment.order.shipping_address.longitude
                        }
                    }
                    for assignment in active_assignments
                ]
            }
        
    @staticmethod
    def get_assignment_pickups_from_order_item(order: Order) -> List[Dict[str, float]]:
        pickups = []
        for item in order.items:
            seller = item.seller
            seller_address = seller.user.address

            if not seller_address:
                continue

            pickups.append({
                "lat": seller_address.latitude,
                "lng": seller_address.longitude
            })
        return pickups

    @staticmethod
    def update_assignment_status(user_id: str, assignment_id: str, new_status: str) -> Dict:
        with session_scope() as session:
            assignment = session.query(DeliveryOrderAssignment).filter_by(assignment_id=assignment_id, delivery_user_id=user_id).first()
            if not assignment:
                logger.warning(f"No active assignment found with ID {assignment_id} for user {user_id}")
                raise NotFoundError("Active assignment not found")

            # Parse new_status string to LogisticalStatus Enum
            try:
                logistical_status = LogisticalStatus[new_status.upper()]
            except KeyError:
                logger.warning(f"Invalid status transition: {new_status} is not a valid LogisticalStatus for assignment {assignment_id}")
                raise ValidationError("Invalid status value")

            # Validate status transition
            if assignment.logistical_status == LogisticalStatus.DELIVERED_PENDING_QR and logistical_status != LogisticalStatus.DELIVERED_PENDING_QR:
                logger.warning(f"Invalid status transition from {assignment.logistical_status} to {logistical_status} for assignment {assignment_id}")
                raise ValidationError("Invalid status transition")

            assignment.logistical_status = logistical_status
            session.commit()

            return {"status": assignment.logistical_status.value}
        
    @staticmethod
    def get_order_qr_code(user_id: str, order_id: str) -> Dict:
        with session_scope() as session:
            assignment = session.query(DeliveryOrderAssignment).filter_by(order_id=order_id, delivery_user_id=user_id, status=AssignmentStatus.ACCEPTED).first()
            if not assignment:
                logger.warning(f"No accepted assignment found for order {order_id} and user {user_id}")
                raise NotFoundError("Accepted assignment not found")

            return {"qrCode": assignment.escrow_qr_code, "orderId": order_id}
    
    @staticmethod
    def confirm_order_qr_code(user_id: str, order_id: str, qr_code: str) -> Dict:
        with session_scope() as session:
            # query the assignment to get the escrow QR code
            assignment = session.query(DeliveryOrderAssignment).filter_by(order_id=order_id, delivery_user_id=user_id, status=AssignmentStatus.ACCEPTED).first()
            if not assignment:
                logger.warning(f"No accepted assignment found for order {order_id} and user {user_id}")
                raise NotFoundError("Accepted assignment not found")

            if assignment.escrow_qr_code != qr_code:
                logger.warning(f"Invalid QR code provided for order {order_id} by user {user_id}")
                raise ValidationError("Invalid QR code")

            # Mark the order as delivered
            order = session.query(Order).filter_by(id=order_id).first()
            if not order:
                logger.warning(f"No order found with ID {order_id}")
                raise NotFoundError("Order not found")

            order.status = OrderStatus.DELIVERED
            session.commit()

            return {"status": "success", "message": "Order marked as delivered"}
        

    @staticmethod
    def find_delivery_order_buyer(user_id: str, room_id: str) -> bool:
        """Checks if the user passed is one of the buyers in a delivery order associated with the room"""
        with session_scope() as session:
            # First, get the location room and its associated assignments
            location_room = session.query(LocationUpdateRoom).filter_by(room_id=room_id).first()
            if not location_room:
                logger.warning(f"Room {room_id} not found")
                return False
            
            # Check if the user is a buyer for any order in this room
            assignment = (
                session.query(DeliveryOrderAssignment)
                .join(Order, DeliveryOrderAssignment.order_id == Order.id)
                .filter_by(room_id=room_id)
                .filter(Order.buyer_id == user_id)
                .first()
            )
            if not assignment:
                logger.warning(f"User {user_id} is not authorized for room {room_id}")
                return False
            
            return True