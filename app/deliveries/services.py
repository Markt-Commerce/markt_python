# python imports
import logging
from random import random
from typing import Optional, Dict, Any, List
from enum import Enum
import uuid

# package imports
from sqlalchemy.exc import SQLAlchemyError

# project imports
from external.redis import redis_client
from app.libs.session import session_scope
from app.libs.pagination import Paginator
from app.libs.errors import NotFoundError, ValidationError
from app.libs.email_service import email_service

# app imports
from .models import DeliveryUser, DeliveryLastLocation, DeliveryOrderAssignment, DeliveryStatus, AssignmentStatus, LocationUpdateRoom, OrderLocationMapping
from .schemas import DeliveryStatus

from app.orders.models import Order, OrderStatus
from app.orders.schemas import OrderSchema
from app.orders.services import OrderService

logger = logging.getLogger(__name__)


class DeliveryService:

    CACHE_EXPIRE_SECONDS = 300  # Cache OTP for 5 minutes
    CACHE_KEY_PREFIX = "otp_cache:"

    @staticmethod
    def login_delivery_partner(phone_number: str, otp: str) -> Dict:
        """Authenticate delivery partner and return partner details"""

        """ Validate that the phone number exists, and it is in the correct format. """
        if not phone_number or not phone_number.isdigit() or len(phone_number) != 10:
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

                return {
                    "partner": {
                        "id": delivery_user.id,
                        "name": delivery_user.name,
                        "status": delivery_user.status,
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
            otp = f"{random.randint(100000, 999999)}"

            #attempt to get delivery partner's email from database using phone number
            with session_scope() as session:
                delivery_user = session.query(DeliveryUser).filter_by(phone_number=phone_number).first()
                if not delivery_user:
                    logger.warning(f"No delivery partner found with phone number {phone_number}")
                    return False

                email = delivery_user.email
                if not email:
                    logger.warning(f"No email found for delivery partner with phone number {phone_number}")
                    return False
            cache_key = f"{DeliveryService.CACHE_KEY_PREFIX}{phone_number}"
            redis_client.setex(cache_key, DeliveryService.CACHE_EXPIRE_SECONDS, otp)

            # Send OTP via email (mocked)
            logger.info(f"Sending OTP {otp} to {email}")
            email_service.send_otp_email(email, otp)
            return {"status": "success", "message": f"OTP sent to {email}"}
        except Exception as e:
            logger.error(f"Error sending OTP: {str(e)}")
            return {"status": "error", "message": "Failed to send OTP"}



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
                    "status": delivery_user.status,
                    "vehicleType": delivery_user.vehicle_type,
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

                return {"status": delivery_user.status}
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
    #TODO: work on this tomorrow properly, getting all the required data
    @staticmethod
    def get_available_orders(user_id: str) -> Dict:
        """Get available orders for the delivery partner"""

        # constant search radius.
        search_radius = 3000
        try:
            with session_scope() as session:
                delivery_user = session.query(DeliveryUser).filter_by(user_id=user_id).first()
                if not delivery_user:
                    logger.warning(f"No delivery partner found for user ID {user_id}")
                    raise NotFoundError("Delivery partner not found")


                """ SELECT longtitude, latitude FROM """

                # Fetch available orders for the delivery user
                available_orders = session.query(Order).filter_by(delivery_user_id=delivery_user.id, status=OrderStatus.AVAILABLE).all()

                return {
                    "range_meters": 3000,
                    "orders": [
                        {
                            "order_id": order.id,
                            "pickup": {
                                "lat": order.pickup_location.lat,
                                "lng": order.pickup_location.lng
                            },
                            "dropoff": {
                                "lat": order.dropoff_location.lat,
                                "lng": order.dropoff_location.lng
                            },
                            "distance_meters": order.distance_meters,
                            "estimated_earnings": order.estimated_earnings
                        }
                        for order in available_orders
                    ]
                }
        except Exception as e:
            logger.error(f"Error fetching available orders: {str(e)}")
            raise NotFoundError("Failed to fetch available orders")

    @staticmethod
    def accept_order(user_id: str, order_id: str) -> Dict:
        with session_scope() as session:
            assignments = session.query(DeliveryOrderAssignment).filter_by(order_id=order_id).all()
            if any(a.status == "ACCEPTED" for a in assignments):
                logger.warning(f"Order {order_id} has already been accepted by another delivery partner")
                raise NotFoundError("Order already accepted")

            if any(a.delivery_user_id == user_id and a.status == "REJECTED" for a in assignments):
                logger.warning(f"Delivery partner {user_id} has already rejected order {order_id}")
                raise NotFoundError("You have already rejected this order")

            # Create a new assignment for the delivery user
            new_assignment = DeliveryOrderAssignment(
                delivery_user_id=user_id,
                order_id=order_id,
                status="ACCEPTED",
                assignment_id=str(uuid.uuid4()),
                escrow_qr_code=str(uuid.uuid4())
            )
            session.add(new_assignment)
            session.commit()

            return {"status": AssignmentStatus.ASSIGNED, "assignmentId": new_assignment.assignment_id}
        
    @staticmethod
    def reject_order(user_id: str, order_id: str) -> Dict:
        with session_scope() as session:
            assignments = session.query(DeliveryOrderAssignment).filter_by(order_id=order_id).all()
            if any(a.status == "ACCEPTED" for a in assignments):
                logger.warning(f"Order {order_id} has already been accepted by another delivery partner")
                raise NotFoundError("Order already accepted")

            if any(a.delivery_user_id == user_id and a.status == "REJECTED" for a in assignments):
                logger.warning(f"Delivery partner {user_id} has already rejected order {order_id}")
                raise NotFoundError("You have already rejected this order")

            # Create a new assignment for the delivery user
            new_assignment = DeliveryOrderAssignment(
                delivery_user_id=user_id,
                order_id=order_id,
                status="REJECTED",
                assignment_id=str(uuid.uuid4())
            )
            session.add(new_assignment)
            session.commit()

            return {"status": AssignmentStatus.ASSIGNED, "assignmentId": new_assignment.assignment_id}
    
    #TODO: We would need to include the location details of the pickup point and drop off points
    @staticmethod
    def get_active_assignments(user_id: str) -> Dict:
        with session_scope() as session:
            active_assignments = session.query(DeliveryOrderAssignment).filter_by(delivery_user_id=user_id, status="ACCEPTED").all()
            #TODO: We would need to include the location details of the pickup point and drop off points, we can get that from the Order model using the order_id in the assignment
            #NOTE: pickup and dropoff location details are not included in the current implementation of the Order model, we would need to add that in order to return the required data for the active assignments endpoint
            return {
                "assignments": [
                    {
                        "assignmentId": assignment.assignment_id,
                        "orderId": assignment.order_id,
                        "assignedAt": assignment.assigned_at.isoformat(),
                        "status": assignment.status,
                        "pickup": {
                            "lat": assignment.pickup_location.lat,
                            "lng": assignment.pickup_location.lng
                        },
                        "dropoff": {
                            "lat": assignment.dropoff_location.lat,
                            "lng": assignment.dropoff_location.lng
                        }
                    }
                    for assignment in active_assignments
                ]
            }
        
    @staticmethod
    def update_assignment_status(user_id: str, assignment_id: str, new_status: str) -> Dict:
        with session_scope() as session:
            assignment = session.query(DeliveryOrderAssignment).filter_by(assignment_id=assignment_id, delivery_user_id=user_id).first()
            if not assignment:
                logger.warning(f"No active assignment found with ID {assignment_id} for user {user_id}")
                raise NotFoundError("Active assignment not found")

            # Validate status transition
            if assignment.status == "DELIVERED" and new_status != "DELIVERED_PENDING_QR":
                logger.warning(f"Invalid status transition from {assignment.status} to {new_status} for assignment {assignment_id}")
                raise ValidationError("Invalid status transition")

            assignment.status = new_status
            session.commit()

            return {"status": assignment.status}
        
    @staticmethod
    def get_order_qr_code(user_id: str, order_id: str) -> Dict:
        with session_scope() as session:
            assignment = session.query(DeliveryOrderAssignment).filter_by(order_id=order_id, delivery_user_id=user_id, status="ACCEPTED").first()
            if not assignment:
                logger.warning(f"No accepted assignment found for order {order_id} and user {user_id}")
                raise NotFoundError("Accepted assignment not found")

            return {"qrCode": assignment.escrow_qr_code, "orderId": order_id}
    
    @staticmethod
    def confirm_order_qr_code(user_id: str, order_id: str, qr_code: str) -> Dict:
        with session_scope() as session:
            # query the order from the db, join the assignment where the order ids are alike, and filter by accepted status
            assignment = session.query(Order).join(DeliveryOrderAssignment, Order.id == DeliveryOrderAssignment.order_id).filter(DeliveryOrderAssignment.delivery_user_id == user_id, DeliveryOrderAssignment.status == "ACCEPTED", Order.id == order_id).first()
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
    def find_delivery_order_buyer(user_id: str, delivery_user_id: str) -> bool:
        #user_id is for buyers or sellers
        """ Checks if the user passed is one of the buyers the delivery is assigned to """
        with session_scope() as session:
            room = session.query(LocationUpdateRoom).filter_by(delivery_user_id=delivery_user_id).first()
            if not room:
                return False
            order_mapping = session.query(OrderLocationMapping).filter_by(room_id=room.room_id).first()
            if not order_mapping:
                return False
            return True