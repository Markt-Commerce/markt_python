from enum import Enum
from external.database import db
from sqlalchemy.dialects.postgresql import JSONB
from app.libs.models import BaseModel

class DeliveryStatus(Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


class DeliveryVehicleType(Enum):
    BIKE = "BIKE"
    CAR = "CAR"
    VAN = "VAN"
    TRUCK = "TRUCK"

class AssignmentStatus(Enum):
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"

class LogisticalStatus(Enum):
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
    room_id = db.Column(db.String(36), db.ForeignKey("location_update_rooms.room_id"), nullable=True)  # Link to location room
    assigned_at = db.Column(db.DateTime, server_default=db.func.now())
    status = db.Column(db.Enum(AssignmentStatus), nullable=False)  # ASSIGNED, ACCEPTED, REJECTED
    logistical_status = db.Column(db.Enum(LogisticalStatus), nullable=True)  # ARRIVED_PICKUP, PICKED_UP, EN_ROUTE_TO_DROPOFF, DELIVERED_PENDING_QR
    escrow_qr_code = db.Column(db.String(255), nullable=False)  # QR code for escrow release, if applicable

    delivery_user = db.relationship("DeliveryUser", backref="order_assignments")
    location_room = db.relationship("LocationUpdateRoom", back_populates="assignments")

# there is the possibility that this would not be stored permanently
# this would be because at the end of the delivery, the room can be cleaned up
class LocationUpdateRoom(BaseModel):
    __tablename__ = "location_update_rooms"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(36), unique=True, nullable=False)  # UUID for room identification
    delivery_user_id = db.Column(db.Integer, db.ForeignKey("delivery_users.id"), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Relationships
    delivery_user = db.relationship("DeliveryUser", backref="location_rooms")
    assignments = db.relationship("DeliveryOrderAssignment", back_populates="location_room", cascade="all, delete-orphan")
    orders = db.relationship("OrderLocationMapping", back_populates="location_room", cascade="all, delete-orphan")


# might be redundant
# we might end up removing this table
class OrderLocationMapping(BaseModel):
    __tablename__ = "order_location_mappings"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, nullable=False)  # Assuming order_id is an integer
    room_id = db.Column(db.String(36), db.ForeignKey("location_update_rooms.room_id"), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Relationship
    location_room = db.relationship("LocationUpdateRoom", back_populates="orders")