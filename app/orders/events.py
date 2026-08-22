"""Event / audit log with transactional outbox (14.2).

Every important order/item/fulfilment state change emits an append-only
`OrderEvent`. Two things distinguish this from every other model/service
pair in this codebase:

1. Current state is still stored directly on Order/OrderItem/
   FulfilmentAllocation/etc, same as always -- this log is NOT the source
   of truth and nothing reconstructs state from it. It exists for audit,
   disputes, and buyer-facing fulfilment-history transparency (15).

2. `OrderEventService.emit()` takes the CALLER'S ALREADY-OPEN session,
   rather than opening its own `session_scope()` the way every other
   service in this codebase does. This is deliberate, not an oversight:
   the whole point of a transactional outbox is that the event write
   commits or rolls back atomically with the state change it's recording
   -- "write the event in the same DB transaction as the state change...
   otherwise a crash between 'update state' and 'emit event' loses or
   fabricates audit entries, precisely where buyer transparency and
   dispute resolution can least afford to be wrong" (spec's own words).
   Every call site below is therefore made from inside an existing
   `with session_scope() as session:` block, passing that same `session`.

Correlation id (15 "tracing"): `order_id` itself is the correlation
anchor threaded through Order -> OrderItem -> FulfilmentAllocation (via
order_item_id) -> Payment -> delivery, rather than a separate synthetic
id -- see the Phase 7 checklist note for the reasoning. Every OrderEvent
row carries it.
"""

from enum import Enum
from typing import Any, Dict, Optional

from external.database import db
from app.libs.models import BaseModel


class OrderEventType(Enum):
    ORDER_CREATED = "order_created"
    ORDER_CANCELLED = "order_cancelled"
    ITEM_ALLOCATED = "item_allocated"
    ITEM_ACCEPTED = "item_accepted"
    ITEM_DECLINED = "item_declined"
    ITEM_TIMED_OUT = "item_timed_out"
    ITEM_CANCELLED_BY_SELLER = "item_cancelled_by_seller"
    ITEM_REROUTED = "item_rerouted"
    ITEM_UNFULFILLED = "item_unfulfilled"
    ITEM_ESCALATED = "item_escalated"
    ITEM_SUBSTITUTION_PENDING = "item_substitution_pending"
    ITEM_SUBSTITUTION_APPROVED = "item_substitution_approved"
    ITEM_SUBSTITUTION_REJECTED = "item_substitution_rejected"
    ITEM_REFUNDED = "item_refunded"
    ITEM_DELIVERED = "item_delivered"


class ActorType(Enum):
    BUYER = "buyer"
    SELLER = "seller"
    RIDER = "rider"
    SYSTEM = "system"


class OrderEvent(BaseModel):
    __tablename__ = "order_events"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(12), db.ForeignKey("orders.id"), nullable=False)
    # Nullable: an order-level event (ORDER_CREATED/ORDER_CANCELLED) has no
    # single item to anchor to.
    order_item_id = db.Column(
        db.Integer, db.ForeignKey("order_items.id"), nullable=True
    )
    event_type = db.Column(db.Enum(OrderEventType), nullable=False)
    actor_type = db.Column(db.Enum(ActorType), nullable=False)
    # String, not FK -- the actor can be a buyer's user id, a seller's id,
    # a rider's id, or absent (actor_type SYSTEM), so a single typed FK
    # doesn't fit.
    actor_id = db.Column(db.String(20), nullable=True)
    event_metadata = db.Column(db.JSON, nullable=True)
    idempotency_key = db.Column(db.String(150), unique=True, nullable=True)

    order = db.relationship("Order")
    order_item = db.relationship("OrderItem")


class OrderEventService:
    @staticmethod
    def emit(
        session,
        order_id: str,
        event_type: OrderEventType,
        actor_type: ActorType = ActorType.SYSTEM,
        order_item_id: Optional[int] = None,
        actor_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Optional[OrderEvent]:
        """Write one event using the CALLER'S session -- see module
        docstring. Never call session_scope() here.

        idempotency_key is optional: only worth supplying at a call site a
        worker could plausibly retry (a scheduled task re-processing the
        same stale allocation). A duplicate key is a silent no-op (returns
        the existing row) rather than a conflict error, matching
        WalletService.credit's existing convention for the same reason.
        """
        if idempotency_key:
            existing = (
                session.query(OrderEvent)
                .filter_by(idempotency_key=idempotency_key)
                .first()
            )
            if existing:
                return existing

        event = OrderEvent(
            order_id=order_id,
            order_item_id=order_item_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            event_metadata=metadata or {},
            idempotency_key=idempotency_key,
        )
        session.add(event)
        session.flush()
        return event
