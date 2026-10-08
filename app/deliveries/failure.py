"""Typed delivery-failure reporting and recovery resolution (10.7).

Both delivery models report through here. The run flow came first; the
single-order flow had no failure path at all, so a rider at a door with
nobody behind it could complete the delivery, or abandon it, and
nothing else -- there was no way to say what had happened. The
DeliveryFailure row is the same shape either way, which the table
already anticipated: delivery_run_id is nullable and its docstring says
"within a run or otherwise".

What differs is only what it does to the rider's own assignment. A run
carries other orders, so the rider keeps it and works on. A single
order is the whole job, so their assignment goes to FAILED -- which
frees their concurrency slot, drops it out of "carrying", and puts the
order back on the board for someone else. AssignmentStatus.FAILED was
added for exactly this and was, until now, unreachable from this path.

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
from app.orders.models import Order, OrderItem

from .models import (
    AssignmentStatus,
    DeliveryCostBearer,
    DeliveryFailure,
    DeliveryFailureOutcome,
    DeliveryFailureReason,
    DeliveryOrderAssignment,
    DeliveryRecoveryAction,
    DeliveryRunAssignment,
    DeliveryRunOrder,
    LogisticalStatus,
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


def _is_perishable(session, order) -> bool:
    """10.5: perishables need the fastest recovery path, so this is
    computed once at report time rather than re-derived by whoever picks
    the failure up."""
    product_ids = {
        item.product_id
        for item in (getattr(order, "items", None) or [])
        if item.status != OrderItem.Status.CANCELLED
    }
    if not product_ids:
        return False
    return (
        session.query(ProductHandling)
        .filter(
            ProductHandling.product_id.in_(product_ids),
            ProductHandling.handling_class == HandlingClass.PERISHABLE,
        )
        .first()
        is not None
    )


def _notify_buyer_of_failure(buyer_user_id, order_id, reason) -> None:
    """Told after the transaction commits, never inside it.

    create_notification opens its own session_scope, so calling it while
    the caller's transaction is still open would commit that transaction
    early -- see app.fulfilment.rerouting._notify_buyer_item_unfulfilled
    for the fuller story.
    """
    if not buyer_user_id:
        return
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
            "Failed to notify buyer of delivery failure for order %s", order_id
        )


def record_abandoned_run(session, run_id: str, user_id: str) -> list:
    """Open a recovery record for every parcel a departing rider holds.

    A run given up after collecting used to leave nothing behind: the
    run was held at RIDER_FAILED, the goods were in somebody's bag, and
    no record anywhere said so. The resolution machinery already exists
    -- resolve_failure picks an action and who pays, complete_recovery
    records that it happened -- but nothing was creating the failures
    that feed it, so a stranded parcel had no representation at all.

    One failure per affected order, because recovery is decided per
    order: the buyer of a collected parcel may get a redelivery while
    the parcel beside it goes back to its seller.

    "Affected" means the goods have left the shop. An order whose
    seller the rider never reached is untouched -- it rides along when
    the run is reassigned, and opening a failure for it would put a
    decision in front of somebody that does not need making.

    Returns the order ids, so the caller can tell the rider exactly
    what they are still carrying.
    """
    from .models import DeliveryRunOrder, DeliveryRunStop, DeliveryRunStopStatus

    collected_sellers = {
        stop.seller_id
        for stop in session.query(DeliveryRunStop)
        .filter_by(delivery_run_id=run_id)
        .all()
        if stop.status == DeliveryRunStopStatus.PICKED_UP
    }
    if not collected_sellers:
        return []

    run_orders = session.query(DeliveryRunOrder).filter_by(delivery_run_id=run_id).all()
    order_ids = [ro.order_id for ro in run_orders]
    if not order_ids:
        return []

    orders = session.query(Order).filter(Order.id.in_(order_ids)).all()

    # Anything already reported for this run stays as it is -- a rider
    # who reported a failed drop and then broke down should not end up
    # with two open records for the same parcel.
    already = {
        failure.order_id
        for failure in session.query(DeliveryFailure)
        .filter(
            DeliveryFailure.delivery_run_id == run_id,
            DeliveryFailure.outcome != DeliveryFailureOutcome.COMPLETED,
        )
        .all()
    }

    affected = []
    for order in orders:
        if order.id in already:
            continue
        holds_goods = any(
            item.seller_id in collected_sellers
            for item in (getattr(order, "items", None) or [])
            if item.status != OrderItem.Status.CANCELLED
        )
        if not holds_goods:
            continue

        session.add(
            DeliveryFailure(
                delivery_run_id=run_id,
                order_id=order.id,
                reason=DeliveryFailureReason.RIDER_UNABLE,
                reported_by_delivery_user_id=user_id,
                report_notes="Rider could not continue the run while carrying this.",
                is_perishable=_is_perishable(session, order),
                outcome=DeliveryFailureOutcome.PENDING,
            )
        )
        OrderEventService.emit(
            session,
            order_id=order.id,
            event_type=OrderEventType.ITEM_DELIVERY_FAILED,
            actor_type=ActorType.RIDER,
            actor_id=user_id,
            metadata={
                "reason": DeliveryFailureReason.RIDER_UNABLE.value,
                "delivery_run_id": run_id,
            },
        )
        affected.append(order.id)

    return affected


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

            is_perishable = _is_perishable(session, run_order.order)

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

            # The buyer's tracker too. It was told a rider had been
            # requested and then nothing ever again -- including this,
            # which is the one state change they most need to see.
            from app.delivery_pricing.order_delivery import (
                DeliveryState,
                advance_buyer_delivery,
            )

            advance_buyer_delivery(session, order_id, DeliveryState.FAILED)

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
        _notify_buyer_of_failure(buyer_user_id, order_id, reason)

        return result

    @staticmethod
    def report_single_order_failure(
        user_id: str,
        assignment_id: str,
        reason: DeliveryFailureReason,
        notes: Optional[str] = None,
    ) -> dict:
        """A rider reports that a single-order delivery could not be made.

        The run flow has had this since 10.7; the single-order flow had
        nothing. A rider at a door with nobody behind it could mark the
        delivery complete, which is a lie, or walk away and leave the
        assignment open forever. Neither told the buyer anything.

        The recorded failure is identical to a run's -- same table, same
        reason enum, same admin-gated resolution -- with delivery_run_id
        left null, which is what that nullable column is for.

        What differs is the rider's own assignment. A run carries other
        orders and the rider works on; a single order is the whole job,
        so the assignment goes to FAILED. That frees their concurrency
        slot, drops it out of "carrying", and -- because
        get_available_orders only hides orders with an ACCEPTED
        assignment -- puts it back on the board for someone else.

        Deliberately no cooldown against the reporting rider: a bad
        address is a bad address for the next rider too, and the honest
        answer to that is a support decision (resolve_failure), not a
        timer. Worth revisiting if riders start bouncing orders.
        """
        with session_scope() as session:
            assignment = (
                session.query(DeliveryOrderAssignment)
                .filter_by(
                    assignment_id=assignment_id,
                    delivery_user_id=user_id,
                    status=AssignmentStatus.ACCEPTED,
                )
                .first()
            )
            if not assignment:
                raise NotFoundError("No active delivery found to report")

            if assignment.logistical_status == LogisticalStatus.COMPLETED:
                raise ConflictError("This delivery is already confirmed as delivered")

            order_id = assignment.order_id
            order = session.query(Order).filter_by(id=order_id).first()

            failure = DeliveryFailure(
                # Null: there is no run. The column is nullable for
                # exactly this case.
                delivery_run_id=None,
                order_id=order_id,
                reason=reason,
                reported_by_delivery_user_id=user_id,
                report_notes=notes,
                is_perishable=_is_perishable(session, order),
                outcome=DeliveryFailureOutcome.PENDING,
            )
            session.add(failure)
            session.flush()

            OrderEventService.emit(
                session,
                order_id=order_id,
                event_type=OrderEventType.ITEM_DELIVERY_FAILED,
                actor_type=ActorType.RIDER,
                actor_id=user_id,
                metadata={"reason": reason.value, "assignment_id": assignment_id},
            )

            # The one state change the buyer most needs to see.
            from app.delivery_pricing.order_delivery import (
                DeliveryState,
                advance_buyer_delivery,
            )

            advance_buyer_delivery(session, order_id, DeliveryState.FAILED)

            # Releases the rider, and the order with them.
            assignment.status = AssignmentStatus.FAILED

            buyer_user_id = getattr(
                getattr(getattr(order, "buyer", None), "user", None), "id", None
            )

            logger.warning(
                "Single-order delivery failure: order %s, assignment %s, " "reason %s",
                order_id,
                assignment_id,
                reason.value,
            )

            result = _serialize(failure)

        _notify_buyer_of_failure(buyer_user_id, order_id, reason)

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
