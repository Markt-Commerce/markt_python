"""Seller fulfilment: accept/decline/timeout of an item allocation
(§12.1-12.2).

Distinct from OrderItem's own PENDING/PROCESSING/SHIPPED/DELIVERED/
CANCELLED lifecycle (Phase 1) -- this tracks the seller-facing negotiation
for who fulfils an item, which OrderItem's state machine knows nothing
about. Deliberately NOT wired to affect OrderItem.status: a decline or
timeout routes to REROUTING (§12.2), and there's no rerouting engine yet
(Phase 6) to resolve that state, so gating OrderItem's progression on
seller acceptance today would strand orders with no recovery path. This
module is Phase 5's own tracking/notification/timeout layer, built and
functional on its own terms, ready for Phase 6 to consume once it exists.
"""

from datetime import datetime, timedelta

from external.database import db
from app.libs.errors import ConflictError, NotFoundError
from app.libs.session import session_scope
from app.notifications.models import NotificationType
from app.notifications.services import NotificationService
from app.orders.models import Order, OrderItem
from app.payments.models import PaymentStatus
from app.users.models import Seller

from .models import FulfilmentAllocation, FulfilmentAllocationStatus

# Phase 0 decision.
SELLER_RESPONSE_TIMEOUT_MINUTES = 3


class FulfilmentService:
    @staticmethod
    def create_allocation(
        order_item_id: int, seller_id: int, quantity: int
    ) -> FulfilmentAllocation:
        """Open the seller-acceptance window for a just-created order item.
        The seller is already determined (set on the item at listing time
        in this codebase -- there's no seller-ranking/selection step yet,
        Phase 6), so this starts directly at AWAITING_SELLER rather than
        the spec's PENDING/SELLER_SELECTION pre-states."""
        with session_scope() as session:
            allocation = FulfilmentAllocation(
                order_item_id=order_item_id,
                seller_id=seller_id,
                quantity=quantity,
                status=FulfilmentAllocationStatus.AWAITING_SELLER,
                seller_response_deadline=datetime.utcnow()
                + timedelta(minutes=SELLER_RESPONSE_TIMEOUT_MINUTES),
            )
            session.add(allocation)
            session.flush()

            seller = session.query(Seller).get(seller_id)
            seller_user_id = seller.user_id if seller else None
            allocation_id = allocation.id

        if seller_user_id:
            NotificationService.create_notification(
                user_id=seller_user_id,
                notification_type=NotificationType.FULFILMENT_REQUEST,
                reference_type="fulfilment_allocation",
                reference_id=str(allocation_id),
                metadata_={
                    "message": (
                        f"New order item to fulfil: {quantity} unit(s). "
                        f"Respond within {SELLER_RESPONSE_TIMEOUT_MINUTES} minutes."
                    )
                },
            )

        with session_scope() as session:
            return session.query(FulfilmentAllocation).get(allocation_id)

    @staticmethod
    def accept(allocation_id: int, seller_id: int) -> FulfilmentAllocation:
        """§12.2 row 1: seller accepts. Required conditions ("reservation
        still active; item not already owned") are enforced structurally --
        the transition guard only allows this from AWAITING_SELLER, and the
        partial unique index guarantees at most one active allocation ever
        exists per item, so there's nothing else to double-own."""
        with session_scope() as session:
            allocation = (
                session.query(FulfilmentAllocation)
                .filter_by(id=allocation_id, seller_id=seller_id)
                .first()
            )
            if not allocation:
                raise NotFoundError("Fulfilment allocation not found")

            allocation.transition_to(FulfilmentAllocationStatus.ACCEPTED)
            session.flush()
            return allocation

    @staticmethod
    def decline(allocation_id: int, seller_id: int) -> FulfilmentAllocation:
        """§12.2 row 2: seller declines, immediately entering REROUTING
        (§12.2 row 4: TIMEOUT -> REROUTING is automatic, and a decline is
        the same "this seller is out" signal, just faster than a timeout)."""
        with session_scope() as session:
            allocation = (
                session.query(FulfilmentAllocation)
                .filter_by(id=allocation_id, seller_id=seller_id)
                .first()
            )
            if not allocation:
                raise NotFoundError("Fulfilment allocation not found")

            allocation.transition_to(FulfilmentAllocationStatus.DECLINED)
            allocation.transition_to(FulfilmentAllocationStatus.REROUTING)
            session.flush()
            return allocation

    @staticmethod
    def start_preparing(allocation_id: int, seller_id: int) -> FulfilmentAllocation:
        """§12.2: ACCEPTED -> PREPARING. Gated on Payment.status ==
        COMPLETED rather than the spec's "escrow authorized" -- re-scoped
        per the Phase 4 cross-cutting blocker: Markt captures the full
        payment before the order even exists, so by the time any
        allocation exists at all, payment is already COMPLETED. This check
        is a defensive invariant, not a real gate in practice."""
        with session_scope() as session:
            allocation = (
                session.query(FulfilmentAllocation)
                .options(
                    db.joinedload(FulfilmentAllocation.order_item)
                    .joinedload(OrderItem.order)
                    .joinedload(Order.payments)
                )
                .filter_by(id=allocation_id, seller_id=seller_id)
                .first()
            )
            if not allocation:
                raise NotFoundError("Fulfilment allocation not found")

            order = allocation.order_item.order
            has_completed_payment = any(
                p.status == PaymentStatus.COMPLETED for p in (order.payments or [])
            )
            if not has_completed_payment:
                raise ConflictError("Cannot start preparing before payment is captured")

            allocation.transition_to(FulfilmentAllocationStatus.PREPARING)
            session.flush()
            return allocation

    @staticmethod
    def expire_stale_allocations() -> dict:
        """Worker (§12.2 row 3): AWAITING_SELLER past its response deadline
        -> TIMEOUT -> REROUTING (row 4, automatic). REROUTING has no
        consumer yet (Phase 6), so this is where a timed-out allocation
        currently comes to rest."""
        now = datetime.utcnow()
        timed_out = 0
        with session_scope() as session:
            stale = (
                session.query(FulfilmentAllocation)
                .filter(
                    FulfilmentAllocation.status
                    == FulfilmentAllocationStatus.AWAITING_SELLER,
                    FulfilmentAllocation.seller_response_deadline < now,
                )
                .all()
            )
            for allocation in stale:
                allocation.transition_to(FulfilmentAllocationStatus.TIMEOUT)
                allocation.transition_to(FulfilmentAllocationStatus.REROUTING)
                timed_out += 1

        return {"timed_out": timed_out}
