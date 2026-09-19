"""The delivery half of an order.

A separate row rather than columns on Order, for the same reason
DeliveryRunOrder is a join table rather than a column: delivery has its own
lifecycle that outlives the order's payment status, and an order can be
cancelled while its delivery is mid-flight. Keeping them apart means neither
state machine has to know about the other's terminal states.

The quote is snapshotted here in full -- fee, breakdown, strategy, version,
distance. Re-reading the quote row would be enough today, but a quote can be
pruned and a strategy can be replaced, and a fee somebody paid must stay
explainable for as long as the order exists.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from external.database import db
from app.libs.helpers import UniqueIdMixin
from app.libs.models import BaseModel


class DeliveryState(Enum):
    """Where a delivery is, from the buyer's point of view.

    Deliberately coarser than DeliveryRunStatus. That enum describes what a
    rider is doing across a whole batch of orders; this describes what is
    happening to *your* parcel, which is the only question the buyer is
    asking. Mapping one to the other lives in the logistics adapter.
    """

    QUOTED = "quoted"  # fee agreed, nothing paid
    PAID = "paid"  # money secured (captured or held)
    AWAITING_DISPATCH = "awaiting_dispatch"  # paid, no job yet — needs ops eyes
    JOB_CREATED = "job_created"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OrderDelivery(BaseModel, UniqueIdMixin):
    __tablename__ = "order_deliveries"
    id_prefix = "ODL_"

    # One source of truth for legal transitions, matching the pattern
    # OrderItem, Payment, InventoryReservation and DeliveryRun already use.
    VALID_TRANSITIONS = {
        DeliveryState.QUOTED: [DeliveryState.PAID, DeliveryState.CANCELLED],
        DeliveryState.PAID: [
            DeliveryState.JOB_CREATED,
            # Paid but the job could not be created. Not a failure of the
            # order -- the money is good and the buyer is owed a delivery --
            # so it parks somewhere an operator can see it rather than
            # pretending dispatch succeeded.
            DeliveryState.AWAITING_DISPATCH,
            DeliveryState.CANCELLED,
        ],
        DeliveryState.AWAITING_DISPATCH: [
            DeliveryState.JOB_CREATED,
            DeliveryState.CANCELLED,
        ],
        DeliveryState.JOB_CREATED: [
            DeliveryState.ASSIGNED,
            DeliveryState.FAILED,
            DeliveryState.CANCELLED,
        ],
        DeliveryState.ASSIGNED: [
            DeliveryState.PICKED_UP,
            DeliveryState.FAILED,
            DeliveryState.CANCELLED,
        ],
        # Past pickup the parcel is in someone's hands. Cancellation stops
        # being a state change and becomes a return, which is a different
        # process with its own cost -- so it is not a legal transition here.
        DeliveryState.PICKED_UP: [DeliveryState.IN_TRANSIT, DeliveryState.FAILED],
        DeliveryState.IN_TRANSIT: [DeliveryState.DELIVERED, DeliveryState.FAILED],
        # A failed delivery can be retried; the parcel still exists.
        DeliveryState.FAILED: [DeliveryState.ASSIGNED, DeliveryState.CANCELLED],
        DeliveryState.DELIVERED: [],
        DeliveryState.CANCELLED: [],
    }

    id = db.Column(db.String(12), primary_key=True, default=None)
    order_id = db.Column(
        db.String(12), db.ForeignKey("orders.id"), nullable=False, unique=True
    )
    quote_id = db.Column(
        db.String(12), db.ForeignKey("delivery_quotes.id"), nullable=True
    )

    state = db.Column(
        db.Enum(DeliveryState), default=DeliveryState.QUOTED, nullable=False
    )

    # --- quote snapshot ----------------------------------------------------
    fee_minor = db.Column(db.Integer, nullable=False)
    breakdown = db.Column(db.JSON, nullable=False)
    distance_km = db.Column(db.Float, nullable=True)
    strategy = db.Column(db.String(50), nullable=True)
    strategy_version = db.Column(db.String(20), nullable=True)

    pickup_lat = db.Column(db.Float, nullable=True)
    pickup_lng = db.Column(db.Float, nullable=True)
    dropoff_lat = db.Column(db.Float, nullable=True)
    dropoff_lng = db.Column(db.Float, nullable=True)

    # --- batch -------------------------------------------------------------
    # Opt-in, and null for a solo delivery. The buyer chooses; nothing
    # attaches an order to a batch without being asked.
    batch_opt_in = db.Column(db.Boolean, default=False, nullable=False)
    delivery_run_id = db.Column(
        db.String(12), db.ForeignKey("delivery_runs.id"), nullable=True
    )
    # What the buyer would have paid alone. The ceiling a batched share is
    # capped at, so sharing can never cost more than going alone.
    solo_fee_minor = db.Column(db.Integer, nullable=False)
    # What they were finally charged, once a batch closed. Null until then.
    settled_fee_minor = db.Column(db.Integer, nullable=True)

    # --- logistics ---------------------------------------------------------
    external_job_id = db.Column(db.String(100), nullable=True)
    last_status_at = db.Column(db.DateTime, nullable=True)
    failure_reason = db.Column(db.Text, nullable=True)

    order = db.relationship("Order", backref=db.backref("delivery", uselist=False))

    def transition_to(self, new_state: DeliveryState) -> None:
        allowed = OrderDelivery.VALID_TRANSITIONS.get(self.state, [])
        if new_state not in allowed:
            raise ValueError(
                f"Cannot move delivery from {self.state.value} to {new_state.value}"
            )
        self.state = new_state
        self.last_status_at = datetime.utcnow()

    @property
    def is_settled(self) -> bool:
        return self.settled_fee_minor is not None

    @property
    def effective_fee_minor(self) -> int:
        """What the buyer actually owes right now.

        Before a batch closes this is the solo fee, because that is the number
        they agreed to and the ceiling they can be charged.
        """
        return self.settled_fee_minor if self.is_settled else self.solo_fee_minor
