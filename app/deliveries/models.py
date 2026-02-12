from enum import Enum
from external.database import db
from sqlalchemy.dialects.postgresql import JSONB
from app.libs.models import BaseModel

class DeliveryStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


class DeliveryVehicleType:
    BIKE = "BIKE"
    CAR = "CAR"
    VAN = "VAN"
    TRUCK = "TRUCK"

class AssignmentStatus:
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"

class LogisticalStatus:
    ARRIVED_PICKUP = "ARRIVED_PICKUP"
    PICKED_UP = "PICKED_UP"
    EN_ROUTE_TO_DROPOFF = "EN_ROUTE_TO_DROPOFF"
    DELIVERED_PENDING_QR = "DELIVERED_PENDING_QR"

class DeliveryUser(BaseModel):
    __tablename__ = "delivery_users"

    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(15), nullable=False)
    email = db.Column(db.String(100), nullable=True) #we might have to use email for otp as having a phone number message service might be expensive for an MVP
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.Enum(DeliveryStatus), nullable=False)
    vehicle_type = db.Column(db.Enum(DeliveryVehicleType), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    rating = db.Column(db.Float, nullable=True)

    last_location = db.relationship("DeliveryLastLocation", back_populates="delivery_user")


class DeliveryLastLocation(BaseModel):
    __tablename__ = "delivery_last_locations"

    id = db.Column(db.Integer, primary_key=True)
    delivery_user_id = db.Column(db.Integer, db.ForeignKey("delivery_users.id"), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    accuracy = db.Column(db.Float, nullable=True)
    speed = db.Column(db.Float, nullable=True)

    delivery_user = db.relationship("DeliveryUser", back_populates="last_location")

class DeliveryOrderAssignment(BaseModel):
    __tablename__ = "delivery_order_assignments"

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.String(36), unique=True, nullable=False)  # UUID for idempotency
    delivery_user_id = db.Column(db.Integer, db.ForeignKey("delivery_users.id"), nullable=False)
    order_id = db.Column(db.Integer, nullable=False)  # Assuming order_id is an integer
    assigned_at = db.Column(db.DateTime, server_default=db.func.now())
    status = db.Column(db.String(20), nullable=False)  # e.g., ASSIGNED, ACCEPTED, REJECTED
    logistical_status = db.Column(db.String(20), nullable=True)  # e.g., ARRIVED_PICKUP, PICKED_UP, EN_ROUTE_TO_DROPOFF, DELIVERED_PENDING_QR
    escrow_qr_code = db.Column(db.String(255), nullable=False)  # QR code for escrow release, if applicable

    delivery_user = db.relationship("DeliveryUser", backref="order_assignments")