from enum import Enum
from external.database import db
from flask_login import UserMixin
from sqlalchemy.dialects.postgresql import JSONB
from app.libs.models import BaseModel

from app.libs.helpers import UniqueIdMixin


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
    COMPLETED = "COMPLETED"


class DeliveryUser(BaseModel, UserMixin, UniqueIdMixin):
    __tablename__ = "delivery_users"
    id_prefix = "DEL_"

    id = db.Column(db.String(12), primary_key=True)
    phone_number = db.Column(db.String(15), nullable=False, unique=True)
    email = db.Column(
        db.String(100), nullable=True, unique=True
    )  # we might have to use email for otp as having a phone number message service might be expensive for an MVP
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.Enum(DeliveryStatus), nullable=False)
    vehicle_type = db.Column(db.Enum(DeliveryVehicleType), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    rating = db.Column(db.Float, nullable=True)

    last_location = db.relationship(
        "DeliveryLastLocation",
        back_populates="delivery_user",
        cascade="all, delete-orphan",
        uselist=False,
    )

    def __repr__(self):
        return f"<DeliveryUser {self.id}>"

    @property
    def is_active(self):
        # Flask-Login uses this to decide if login is allowed at all.
        # Treat SUSPENDED as blocked; ACTIVE/INACTIVE are allowed to authenticate.
        return self.status != DeliveryStatus.SUSPENDED


class DeliveryLastLocation(BaseModel):
    __tablename__ = "delivery_last_locations"

    id = db.Column(db.Integer, primary_key=True)
    delivery_user_id = db.Column(
        db.String(12),
        db.ForeignKey("delivery_users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    accuracy = db.Column(db.Float, nullable=True)
    speed = db.Column(db.Float, nullable=True)

    delivery_user = db.relationship("DeliveryUser", back_populates="last_location")


class DeliveryOrderAssignment(BaseModel):
    __tablename__ = "delivery_order_assignments"

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(
        db.String(36), unique=True, nullable=False
    )  # UUID for idempotency
    delivery_user_id = db.Column(
        db.String(12), db.ForeignKey("delivery_users.id"), nullable=False
    )
    order_id = db.Column(db.String(12), db.ForeignKey("orders.id"), nullable=False)
    room_id = db.Column(
        db.String(36), db.ForeignKey("location_update_rooms.room_id"), nullable=True
    )  # Link to location room
    assigned_at = db.Column(db.DateTime, server_default=db.func.now())
    status = db.Column(
        db.Enum(AssignmentStatus), nullable=False
    )  # ASSIGNED, ACCEPTED, REJECTED
    logistical_status = db.Column(
        db.Enum(LogisticalStatus), nullable=True
    )  # ARRIVED_PICKUP, PICKED_UP, EN_ROUTE_TO_DROPOFF, DELIVERED_PENDING_QR
    escrow_qr_code = db.Column(
        db.String(255), nullable=True
    )  # QR for escrow release; None for REJECTED assignments

    delivery_user = db.relationship("DeliveryUser", backref="order_assignments")
    order = db.relationship(
        "Order", backref="delivery_assignments", foreign_keys=[order_id]
    )
    location_room = db.relationship("LocationUpdateRoom", back_populates="assignments")


# there is the possibility that this would not be stored permanently
# this would be because at the end of the delivery, the room can be cleaned up
class LocationUpdateRoom(BaseModel):
    __tablename__ = "location_update_rooms"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(
        db.String(36), unique=True, nullable=False
    )  # UUID for room identification
    delivery_user_id = db.Column(
        db.String(12), db.ForeignKey("delivery_users.id"), nullable=True
    )
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Relationships
    delivery_user = db.relationship("DeliveryUser", backref="location_rooms")
    assignments = db.relationship(
        "DeliveryOrderAssignment",
        back_populates="location_room",
        cascade="all, delete-orphan",
    )
    orders = db.relationship(
        "OrderLocationMapping",
        back_populates="location_room",
        cascade="all, delete-orphan",
    )


# might be redundant
# we might end up removing this table
class OrderLocationMapping(BaseModel):
    __tablename__ = "order_location_mappings"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(12), db.ForeignKey("orders.id"), nullable=False)
    room_id = db.Column(
        db.String(36), db.ForeignKey("location_update_rooms.room_id"), nullable=False
    )
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Relationship
    location_room = db.relationship("LocationUpdateRoom", back_populates="orders")


class DeliveryRunStatus(Enum):
    """10.2's run lifecycle, reconciled with 10.7's rider-failure wording
    into one state machine (the spec states them slightly differently in
    the two sections -- this is the single source of truth). RIDER_FAILED
    can return to RIDER_ASSIGNMENT ("a failed run triggers reassignment
    where possible", 10.7) rather than being a dead end.

    Everything from RIDER_ASSIGNMENT onward is scaffolded now (the state
    exists, transitions are defined) but not yet actively driven -- the
    rider-facing accept/decline/pickup/POD flow that walks a run through
    those states is Phase 10, not this one. Phase 9's own workers only
    ever drive OPEN -> CUTOFF_REACHED -> PLANNING (see
    app.deliveries.runs.DeliveryRunService.close_runs_past_cutoff)."""

    OPEN = "open"
    CUTOFF_REACHED = "cutoff_reached"
    PLANNING = "planning"
    RIDER_ASSIGNMENT = "rider_assignment"
    RIDER_ACCEPTED = "rider_accepted"
    PICKUP_IN_PROGRESS = "pickup_in_progress"
    DELIVERY_IN_PROGRESS = "delivery_in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RIDER_FAILED = "rider_failed"
    PARTIALLY_COMPLETED = "partially_completed"


class DeliveryRun(BaseModel, UniqueIdMixin):
    """A batch of orders sharing one dispatch, scoped to one Market -> one
    Area (10.1: "a run serves one market -> one area -> back"). Orders
    attach only once "fully routed and confirmed" (10.1) -- see
    app.deliveries.runs.DeliveryRunService.attach_eligible_orders, which
    is what decides *when* an order is ready, not this model.

    Deliberately does NOT replace app.deliveries' existing single-order
    DeliveryUser/DeliveryOrderAssignment/QR-POD machinery -- that's the
    rider-facing execution layer, which Phase 10 will rework to operate
    per-run instead of per-order. This model is the batching/pricing
    container Phase 9 is actually responsible for."""

    __tablename__ = "delivery_runs"
    id_prefix = "RUN_"

    # Single source of truth for legal transitions, same transition_to
    # pattern as OrderItem/Payment/InventoryReservation/FulfilmentAllocation.
    VALID_STATUS_TRANSITIONS = {
        DeliveryRunStatus.OPEN: [
            DeliveryRunStatus.CUTOFF_REACHED,
            DeliveryRunStatus.CANCELLED,
        ],
        DeliveryRunStatus.CUTOFF_REACHED: [
            DeliveryRunStatus.PLANNING,
            DeliveryRunStatus.CANCELLED,
        ],
        DeliveryRunStatus.PLANNING: [
            DeliveryRunStatus.RIDER_ASSIGNMENT,
            DeliveryRunStatus.CANCELLED,
        ],
        DeliveryRunStatus.RIDER_ASSIGNMENT: [
            DeliveryRunStatus.RIDER_ACCEPTED,
            DeliveryRunStatus.CANCELLED,
        ],
        DeliveryRunStatus.RIDER_ACCEPTED: [
            DeliveryRunStatus.PICKUP_IN_PROGRESS,
            DeliveryRunStatus.CANCELLED,
        ],
        DeliveryRunStatus.PICKUP_IN_PROGRESS: [
            DeliveryRunStatus.DELIVERY_IN_PROGRESS,
            DeliveryRunStatus.RIDER_FAILED,
        ],
        DeliveryRunStatus.DELIVERY_IN_PROGRESS: [
            DeliveryRunStatus.COMPLETED,
            DeliveryRunStatus.PARTIALLY_COMPLETED,
            DeliveryRunStatus.RIDER_FAILED,
        ],
        DeliveryRunStatus.RIDER_FAILED: [
            # 10.7: "a failed run triggers reassignment where possible."
            DeliveryRunStatus.RIDER_ASSIGNMENT,
            DeliveryRunStatus.CANCELLED,
        ],
    }

    id = db.Column(db.String(12), primary_key=True, default=None)
    market_id = db.Column(db.Integer, db.ForeignKey("markets.id"), nullable=False)
    area_id = db.Column(db.Integer, db.ForeignKey("areas.id"), nullable=False)
    status = db.Column(
        db.Enum(DeliveryRunStatus), default=DeliveryRunStatus.OPEN, nullable=False
    )

    # 10.4 capacity -- snapshotted onto the run at creation (from
    # app.deliveries.runs' RUN_MAX_PACKAGES/RUN_MAX_WEIGHT_GRAMS
    # constants) rather than always re-reading the constants live, so a
    # later constant change doesn't retroactively alter what an
    # already-planned run's capacity was understood to be.
    max_packages = db.Column(db.Integer, nullable=False)
    max_weight_grams = db.Column(db.Integer, nullable=False)

    # 10.2/10.3: when this run's OPEN window closes -- set at creation to
    # now + the run cadence (Phase 0: ~2h). The cutoff worker
    # (close_runs_past_cutoff) advances OPEN -> CUTOFF_REACHED once this
    # passes.
    cutoff_at = db.Column(db.DateTime, nullable=False)

    # 10.3 pricing -- null until the cutoff worker computes them (final
    # order count, and therefore the per-order shared price, isn't known
    # until the run stops accepting new orders).
    base_price = db.Column(db.Float, nullable=True)
    price_per_order = db.Column(db.Float, nullable=True)

    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancel_reason = db.Column(db.Text, nullable=True)

    market = db.relationship("Market")
    area = db.relationship("Area")
    run_orders = db.relationship(
        "DeliveryRunOrder", back_populates="delivery_run", cascade="all, delete-orphan"
    )

    def transition_to(self, new_status: "DeliveryRunStatus") -> None:
        """Apply a status change, raising ValueError if it isn't a legal transition."""
        allowed = DeliveryRun.VALID_STATUS_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(f"Cannot transition from {self.status} to {new_status}")
        self.status = new_status


class DeliveryRunWaitChoice(Enum):
    """10.3's thin-volume prompt: the buyer's choice when their run
    doesn't have enough sharing yet. PENDING (the default, before the
    buyer responds) behaves exactly like WAIT -- the spec's own wording
    marks "wait for a fuller run" as the default, so a buyer who never
    answers is treated the same as one who explicitly chose to wait."""

    PENDING = "pending"
    WAIT = "wait"
    PAY_NOW = "pay_now"


class DeliveryRunOrder(BaseModel):
    """Which orders are attached to which run (10.1). A join table rather
    than a column on Order: an order can only ever be in one *active* run
    at a time in practice (enforced by the unique order_id below), but
    keeping this as its own row leaves room for a future reroute-
    triggered run swap or an overflow split to have somewhere to record
    that history without mutating Order itself."""

    __tablename__ = "delivery_run_orders"

    id = db.Column(db.Integer, primary_key=True)
    delivery_run_id = db.Column(
        db.String(12), db.ForeignKey("delivery_runs.id"), nullable=False
    )
    order_id = db.Column(
        db.String(12), db.ForeignKey("orders.id"), nullable=False, unique=True
    )
    joined_at = db.Column(db.DateTime, server_default=db.func.now())

    # 10.3 thin-volume prompt/fallback -- see DeliveryRunWaitChoice and
    # app.deliveries.runs.DeliveryRunService.notify_thin_volume_orders/
    # set_wait_choice/close_runs_past_cutoff's fallback handling.
    wait_choice = db.Column(
        db.Enum(DeliveryRunWaitChoice),
        default=DeliveryRunWaitChoice.PENDING,
        nullable=False,
    )
    # Only meaningful alongside WAIT: did the buyer pre-consent to being
    # charged the single-drop rate if the run still hasn't filled by
    # cutoff? False (the default, including for PENDING/never-responded)
    # means the fallback is free cancellation instead -- see 10.3's own
    # "auto-fall-back to the single-drop rate (with the buyer's up-front
    # consent to that price) or offer free cancellation."
    fallback_consent = db.Column(db.Boolean, default=False, nullable=False)
    # Set once the thin-volume notification has actually been sent, so
    # the periodic sweep doesn't re-notify on every run.
    notified_thin_volume_at = db.Column(db.DateTime, nullable=True)

    delivery_run = db.relationship("DeliveryRun", back_populates="run_orders")
    order = db.relationship("Order")
