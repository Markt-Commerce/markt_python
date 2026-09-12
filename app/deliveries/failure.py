"""Typed delivery-failure reporting and recovery resolution (10.7).

Scope: wired to the run-based delivery flow only (DeliveryRunAssignment/
DeliveryRunOrder) -- the pre-existing single-order flow
(DeliveryOrderAssignment) has no equivalent failure-reporting path yet,
left unwired here (flagged in the Implementation Checklist) rather than
guessed at, since its assignment/auth shape is different enough to need
its own consideration.

Reporting (report_failure) is rider-authenticated, same pattern as the
rest of this run-delivery surface. Resolving *what happens next*
(resolve_failure/complete_recovery) is deliberately gated on
@admin_required at the route level -- deciding a recovery action and who
bears the cost is a support/business decision, not something the
reporting rider settles unilaterally by choosing a reason.
"""

import logging
from datetime import datetime
from typing import Optional

from app.inventory.models import HandlingClass, ProductHandling
from app.libs.errors import ConflictError, NotFoundError, ValidationError
from app.libs.session import session_scope
from app.notifications.models import NotificationType
from app.notifications.services import NotificationService
from app.orders.events import ActorType, OrderEventService, OrderEventType
from app.orders.models import OrderItem

from .models import (
    AssignmentStatus,
    DeliveryCostBearer,
    DeliveryFailure,
    DeliveryFailureOutcome,
    DeliveryFailureReason,
    DeliveryRecoveryAction,
    DeliveryRunAssignment,
    DeliveryRunOrder,
)

logger = logging.getLogger(__name__)


def _serialize(failure: DeliveryFailure) -> dict:
    """Read every attribute while the session is still open, so the
    caller gets a plain dict rather than an ORM instance whose attributes
    may need a fresh (session-bound) query to re-read after commit."""
    return {
        "id": failure.id,
        "delivery_run_id": failure.delivery_run_id,
        "order_id": failure.order_id,
        "reason": failure.reason.value,
        "is_perishable": failure.is_perishable,
        "outcome": failure.outcome.value,
        "recovery_action": (
            failure.recovery_action.value if failure.recovery_action else None
        ),
        "cost_bearer": failure.cost_bearer.value if failure.cost_bearer else None,
        "resolution_notes": failure.resolution_notes,
        "reported_at": failure.reported_at,
        "resolved_at": failure.resolved_at,
        "completed_at": failure.completed_at,
    }


class DeliveryFailureService:
    @staticmethod
    def report_failure(
        user_id: str,
        run_id: str,
        order_id: str,
        reason: DeliveryFailureReason,
        notes: Optional[str] = None,
    ) -> dict:
        """Rider reports a failed delivery attempt for one order within
        their accepted run. Computes is_perishable from the order's own
        items (10.5) so resolution can prioritise it without re-deriving
        this later."""
        with session_scope() as session:
            assignment = (
                session.query(DeliveryRunAssignment)
                .filter_by(
                    delivery_run_id=run_id,
                    delivery_user_id=user_id,
                    status=AssignmentStatus.ACCEPTED,
                )
                .first()
            )
            if not assignment:
                raise NotFoundError("No accepted assignment found for this run")

            run_order = (
                session.query(DeliveryRunOrder)
                .filter_by(delivery_run_id=run_id, order_id=order_id)
                .first()
            )
            if not run_order:
                raise NotFoundError("Order not attached to this run")

            active_item_product_ids = {
                item.product_id
                for item in run_order.order.items
                if item.status != OrderItem.Status.CANCELLED
            }
            is_perishable = False
            if active_item_product_ids:
                is_perishable = (
                    session.query(ProductHandling)
                    .filter(
                        ProductHandling.product_id.in_(active_item_product_ids),
                        ProductHandling.handling_class == HandlingClass.PERISHABLE,
                    )
                    .first()
                    is not None
                )

            failure = DeliveryFailure(
                delivery_run_id=run_id,
                order_id=order_id,
                reason=reason,
                reported_by_delivery_user_id=user_id,
                report_notes=notes,
                is_perishable=is_perishable,
                # Explicit rather than relying on the column default --
                # that only applies at actual DB flush, not at
                # construction (same gap InventoryReservation.reserve_stock
                # hit and fixed the same way, Phase 3).
                outcome=DeliveryFailureOutcome.PENDING,
            )
            session.add(failure)
            session.flush()

            # 14.2/Phase 12 gap-fill: the run-based delivery flow
            # (app.deliveries.pickup/failure) predates the event log's
            # coverage -- this closes it for the failure-reporting moment,
            # same outbox discipline as everywhere else (caller's already-
            # open session, no nested session_scope()).
            OrderEventService.emit(
                session,
                order_id=order_id,
                event_type=OrderEventType.ITEM_DELIVERY_FAILED,
                actor_type=ActorType.RIDER,
                actor_id=user_id,
                metadata={"reason": reason.value, "delivery_run_id": run_id},
            )

            buyer_user_id = (
                run_order.order.buyer.user_id
                if run_order.order and run_order.order.buyer
                else None
            )

            logger.warning(
                "Delivery failure reported: order %s, run %s, reason %s "
                "(perishable=%s)",
                order_id,
                run_id,
                reason.value,
                is_perishable,
            )

            result = _serialize(failure)

        # Phase 12 (15): notify the buyer -- after the transaction above
        # commits, not before. NotificationService.create_notification
        # always opens its own session_scope() to persist the Notification
        # row; calling it while the transaction above is still open would
        # commit that transaction early (see
        # app.fulfilment.rerouting._notify_buyer_item_unfulfilled's own
        # docstring for the fuller story on why that matters).
        if buyer_user_id:
            try:
                NotificationService.create_notification(
                    user_id=buyer_user_id,
                    notification_type=NotificationType.DELIVERY_FAILED,
                    reference_type="order",
                    reference_id=order_id,
                    metadata_={
                        "message": (
                            "A delivery attempt for your order failed. "
                            "We're working on next steps."
                        ),
                        "reason": reason.value,
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to notify buyer of delivery failure for order %s",
                    order_id,
                )

        return result

    @staticmethod
    def resolve_failure(
        failure_id: str,
        recovery_action: DeliveryRecoveryAction,
        cost_bearer: DeliveryCostBearer,
        notes: Optional[str] = None,
    ) -> dict:
        """Records the chosen recovery action and who bears the cost --
        a human/policy decision, not derived here (see DeliveryCostBearer's
        own docstring). Does not itself execute the recovery action (no
        redelivery dispatch, no refund, no physical return/dispose
        workflow) -- see this module's own docstring and the
        Implementation Checklist for what's deliberately left
        unautomated in this increment."""
        with session_scope() as session:
            failure = session.query(DeliveryFailure).get(failure_id)
            if not failure:
                raise NotFoundError("Delivery failure not found")
            if failure.outcome != DeliveryFailureOutcome.PENDING:
                raise ConflictError(
                    f"Failure already at outcome {failure.outcome.value}"
                )

            failure.recovery_action = recovery_action
            failure.cost_bearer = cost_bearer
            failure.resolution_notes = notes
            failure.outcome = DeliveryFailureOutcome.RESOLVED
            failure.resolved_at = datetime.utcnow()

            return _serialize(failure)

    @staticmethod
    def complete_recovery(failure_id: str, notes: Optional[str] = None) -> dict:
        """Marks the (already-decided) recovery action as actually
        carried out -- e.g. the redelivery was attempted, the item was
        returned to the seller, the item was disposed. The physical/
        money-movement side of that action is out of scope here (see
        this module's own docstring); this only records that it
        happened."""
        with session_scope() as session:
            failure = session.query(DeliveryFailure).get(failure_id)
            if not failure:
                raise NotFoundError("Delivery failure not found")
            if failure.outcome != DeliveryFailureOutcome.RESOLVED:
                raise ValidationError(
                    "Failure must be resolved (recovery action decided) "
                    "before it can be marked completed"
                )

            if notes:
                existing = failure.resolution_notes or ""
                failure.resolution_notes = (
                    f"{existing}\n{notes}".strip() if existing else notes
                )
            failure.outcome = DeliveryFailureOutcome.COMPLETED
            failure.completed_at = datetime.utcnow()

            return _serialize(failure)
