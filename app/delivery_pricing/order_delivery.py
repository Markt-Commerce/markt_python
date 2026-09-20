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

import logging
from datetime import datetime
from enum import Enum

from external.database import db
from app.libs.helpers import UniqueIdMixin
from app.libs.models import BaseModel

logger = logging.getLogger(__name__)


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

    # The happy path, in the order a parcel actually travels. Used to walk
    # forward through states nothing reports individually -- see advance_to.
    PROGRESS_PATH = [
        DeliveryState.QUOTED,
        DeliveryState.PAID,
        DeliveryState.JOB_CREATED,
        DeliveryState.ASSIGNED,
        DeliveryState.PICKED_UP,
        DeliveryState.IN_TRANSIT,
        DeliveryState.DELIVERED,
    ]

    def advance_to(self, target: DeliveryState) -> bool:
        """Move forward to `target`, through any states in between.

        `transition_to` is a single legal step and raises otherwise, which
        is right for the dispatch code that calls it: those transitions are
        the point of the call. This is for the rider's progress, where it
        is not.

        Two reasons a plain transition_to is wrong here. A rider reports
        arriving, picking up and setting off, but nothing reports the
        buyer-facing states in between -- so a delivery sitting at
        JOB_CREATED when the rider confirms a pickup has to pass through
        ASSIGNED to get to PICKED_UP, and every order accepted before the
        rider flow drove this state at all is in exactly that position.
        And a rider re-sending a step they already completed must not be
        an error: the parcel has not moved backwards, so neither should
        this.

        Returns whether anything changed. Never raises: this is bookkeeping
        alongside a delivery that has already physically happened.
        """
        if self.state == target:
            return False

        # Off the happy path -- FAILED and CANCELLED are endings reachable
        # from most states, not steps to walk towards, so they are a
        # single legal step or nothing at all.
        if target not in OrderDelivery.PROGRESS_PATH:
            if target in OrderDelivery.VALID_TRANSITIONS.get(self.state, []):
                self.transition_to(target)
                return True
            return False

        # And AWAITING_DISPATCH is a parked state that rejoins the path at
        # JOB_CREATED, which is the only move VALID_TRANSITIONS allows it.
        if self.state == DeliveryState.AWAITING_DISPATCH:
            self.transition_to(DeliveryState.JOB_CREATED)
            if target == DeliveryState.JOB_CREATED:
                return True

        try:
            start = OrderDelivery.PROGRESS_PATH.index(self.state)
            end = OrderDelivery.PROGRESS_PATH.index(target)
        except ValueError:
            # Already ended -- FAILED or CANCELLED. A failed delivery can
            # be retried, but that is a deliberate reassignment, not
            # something a stray status update should do.
            return False

        # Already past it. A delivered parcel does not become in-transit
        # because a duplicate status update arrived late.
        if end <= start:
            return False

        moved = False
        for index in range(start + 1, end + 1):
            step = OrderDelivery.PROGRESS_PATH[index]
            # Stop where the table says stop rather than forcing it. Going
            # as far as the rules allow and reporting honestly beats
            # raising over a step nobody asked about directly.
            if step not in OrderDelivery.VALID_TRANSITIONS.get(self.state, []):
                break
            self.transition_to(step)
            moved = True
        return moved

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


def advance_buyer_delivery(session, order_id: str, target) -> None:
    """Move the buyer's delivery tracker for `order_id` forward to `target`.

    Nothing did this. OrderDelivery.state was driven as far as JOB_CREATED
    by dispatch and then left there for good -- so a buyer watching their
    order saw "Rider requested / Waiting for someone to take it" through
    the entire delivery and after it had arrived, while the tracking
    screen right next to it read Delivered.

    Lives here rather than on DeliveryService because both delivery models
    need it: single-order assignments and batch runs, in modules that
    cannot import each other.

    Never raises. This is bookkeeping alongside a parcel that has already
    physically moved, and a failure to record it must not undo the step
    the rider took.
    """
    if target is None:
        return
    try:
        delivery = session.query(OrderDelivery).filter_by(order_id=order_id).first()
        # Orders checked out before quoting existed have no delivery row,
        # and an absent tracker is not an error.
        if delivery is None:
            return
        delivery.advance_to(target)
    except Exception:
        logger.exception(
            "Could not advance the buyer's delivery tracker for order %s", order_id
        )
