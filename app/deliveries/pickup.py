"""Rider pickup-per-seller-stop and per-order POD within an accepted
DeliveryRun (10.6). A run can batch several sellers' items across several
orders -- pickup is confirmed once per seller (a DeliveryRunStop), and
proof-of-delivery is confirmed once per order (DeliveryRunOrder.pod_status)
once every stop the order depends on has been picked up.

Scope note on 10.6's "POD is per item / per allocation": interpreted here
as per-*order*-within-a-run, not literally per single item inside one
order. A buyer receives their whole order in one handshake today (one QR
per order), same granularity the existing single-order
DeliveryService.confirm_order_qr_code already has -- true single-item-of-
one-order POD would need the buyer to scan multiple independent codes for
what they experience as one delivery, a bigger UX change than this
increment's scope (flagged in the Implementation Checklist). The escrow-
release granularity 10.6 actually cares about already exists structurally
-- WalletService.settle_order_item operates per OrderItem (Phase 0b) and
its settlement-hold worker (Phase 4/8) picks up anything marked DELIVERED
regardless of which POD path set it, so confirm_order_pod below only has
to get OrderItem.status/delivered_at right, the same way
confirm_order_qr_code already does.

Auth pattern deliberately matches the existing single-order QR flow, not
the original spec doc's "buyer app calls the confirm endpoint" framing:
DeliveryService.get_order_qr_code/confirm_order_qr_code are both
rider-authenticated (current_user.id is the DeliveryUser's session, on
the deliveries blueprint's separate auth namespace) -- the buyer's role
in the actual handshake is showing/reading a code, not making an
authenticated API call of their own. Kept consistent here rather than
introducing a second, differently-authenticated pattern.
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, List

from app.libs.errors import ConflictError, NotFoundError, ValidationError
from app.libs.session import session_scope
from app.orders.events import ActorType, OrderEventService, OrderEventType
from app.orders.models import Order, OrderItem, OrderStatus
from app.orders.services import OrderService

from .models import (
    AssignmentStatus,
    DeliveryRun,
    DeliveryRunAssignment,
    DeliveryRunOrder,
    DeliveryRunOrderPodStatus,
    DeliveryRunStatus,
    DeliveryRunStop,
    DeliveryRunStopStatus,
)

logger = logging.getLogger(__name__)


def create_stops_for_run(session, run_id: str) -> List[int]:
    """Called once, right after a rider accepts a run (see
    DeliveryRunAssignmentService.accept_run) -- one DeliveryRunStop per
    distinct seller across every order attached to the run. Idempotent:
    a no-op if stops already exist for this run."""
    existing = session.query(DeliveryRunStop).filter_by(delivery_run_id=run_id).count()
    if existing:
        return []

    run_orders = session.query(DeliveryRunOrder).filter_by(delivery_run_id=run_id).all()
    seller_ids = set()
    for run_order in run_orders:
        order = session.query(Order).get(run_order.order_id)
        if not order:
            continue
        for item in order.items:
            if item.status != OrderItem.Status.CANCELLED:
                seller_ids.add(item.seller_id)

    for seller_id in seller_ids:
        session.add(
            DeliveryRunStop(
                delivery_run_id=run_id,
                seller_id=seller_id,
                status=DeliveryRunStopStatus.PENDING,
            )
        )
    return list(seller_ids)


def _accepted_assignment(session, run_id: str, user_id: str):
    return (
        session.query(DeliveryRunAssignment)
        .filter_by(
            delivery_run_id=run_id,
            delivery_user_id=user_id,
            status=AssignmentStatus.ACCEPTED,
        )
        .first()
    )


class DeliveryRunPickupService:
    @staticmethod
    def arrive_at_stop(user_id: str, run_id: str, seller_id: int) -> Dict:
        with session_scope() as session:
            if not _accepted_assignment(session, run_id, user_id):
                raise NotFoundError("No accepted assignment found for this run")

            stop = (
                session.query(DeliveryRunStop)
                .filter_by(delivery_run_id=run_id, seller_id=seller_id)
                .first()
            )
            if not stop:
                raise NotFoundError("Stop not found for this run")
            if stop.status != DeliveryRunStopStatus.PENDING:
                raise ConflictError(f"Stop already at {stop.status.value}")

            stop.status = DeliveryRunStopStatus.ARRIVED
            stop.arrived_at = datetime.utcnow()

            return {
                "delivery_run_id": run_id,
                "seller_id": seller_id,
                "status": stop.status.value,
            }

    @staticmethod
    def confirm_pickup_at_stop(user_id: str, run_id: str, seller_id: int) -> Dict:
        """Marks a stop PICKED_UP, ships every item from that seller
        across the run's orders (matching the existing single-order
        update_assignment_status's PICKED_UP -> item SHIPPED wiring), and
        -- once every stop in the run is done -- issues a POD QR per
        order and advances the run to DELIVERY_IN_PROGRESS."""
        with session_scope() as session:
            if not _accepted_assignment(session, run_id, user_id):
                raise NotFoundError("No accepted assignment found for this run")

            run = session.query(DeliveryRun).filter_by(id=run_id).first()
            if not run:
                raise NotFoundError("Delivery run not found")

            stop = (
                session.query(DeliveryRunStop)
                .filter_by(delivery_run_id=run_id, seller_id=seller_id)
                .first()
            )
            if not stop:
                raise NotFoundError("Stop not found for this run")
            if stop.status == DeliveryRunStopStatus.PICKED_UP:
                raise ConflictError("Stop already picked up")

            # First pickup of the run kicks it off (10.2).
            if run.status == DeliveryRunStatus.RIDER_ACCEPTED:
                run.transition_to(DeliveryRunStatus.PICKUP_IN_PROGRESS)

            stop.status = DeliveryRunStopStatus.PICKED_UP
            stop.picked_up_at = datetime.utcnow()

            run_orders = (
                session.query(DeliveryRunOrder).filter_by(delivery_run_id=run_id).all()
            )
            for run_order in run_orders:
                order = session.query(Order).get(run_order.order_id)
                if not order:
                    continue
                for item in order.items:
                    if (
                        item.seller_id == seller_id
                        and item.status == OrderItem.Status.PROCESSING
                    ):
                        item.transition_to(OrderItem.Status.SHIPPED)

            remaining = (
                session.query(DeliveryRunStop)
                .filter(
                    DeliveryRunStop.delivery_run_id == run_id,
                    DeliveryRunStop.status != DeliveryRunStopStatus.PICKED_UP,
                )
                .count()
            )

            issued_for_orders = []
            if remaining == 0:
                run.transition_to(DeliveryRunStatus.DELIVERY_IN_PROGRESS)
                for run_order in run_orders:
                    if run_order.pod_status == DeliveryRunOrderPodStatus.PENDING:
                        run_order.pod_status = DeliveryRunOrderPodStatus.QR_ISSUED
                        run_order.qr_code = str(uuid.uuid4())
                        issued_for_orders.append(run_order.order_id)

            return {
                "delivery_run_id": run_id,
                "seller_id": seller_id,
                "status": stop.status.value,
                "run_status": run.status.value,
                "pod_issued_for_orders": issued_for_orders,
            }


class DeliveryRunPodService:
    @staticmethod
    def get_order_pod_qr(user_id: str, run_id: str, order_id: str) -> Dict:
        with session_scope() as session:
            if not _accepted_assignment(session, run_id, user_id):
                raise NotFoundError("No accepted assignment found for this run")

            run_order = (
                session.query(DeliveryRunOrder)
                .filter_by(delivery_run_id=run_id, order_id=order_id)
                .first()
            )
            if not run_order:
                raise NotFoundError("Order not attached to this run")
            if run_order.pod_status != DeliveryRunOrderPodStatus.QR_ISSUED:
                raise ValidationError("Order is not ready for proof-of-delivery yet")

            return {"order_id": order_id, "qr_code": run_order.qr_code or ""}

    @staticmethod
    def confirm_order_pod(
        user_id: str, run_id: str, order_id: str, qr_code: str
    ) -> Dict:
        """Marks every non-cancelled item in the order DELIVERED -- same
        discipline as the existing single-order confirm_order_qr_code --
        so the settlement-hold worker (already per-item, Phase 0b/4/8)
        picks it up without any new wiring. Completes the run once every
        attached order has confirmed."""
        with session_scope() as session:
            if not _accepted_assignment(session, run_id, user_id):
                raise NotFoundError("No accepted assignment found for this run")

            run_order = (
                session.query(DeliveryRunOrder)
                .filter_by(delivery_run_id=run_id, order_id=order_id)
                .first()
            )
            if not run_order:
                raise NotFoundError("Order not attached to this run")
            if not run_order.qr_code or run_order.qr_code != qr_code:
                raise ValidationError("Invalid QR code")
            if run_order.pod_status != DeliveryRunOrderPodStatus.QR_ISSUED:
                raise ValidationError(
                    "Order is not ready for proof-of-delivery confirmation"
                )

            order = session.query(Order).get(order_id)
            if not order:
                raise NotFoundError("Order not found")

            for item in order.items:
                if item.status == OrderItem.Status.CANCELLED:
                    continue
                if item.status != OrderItem.Status.DELIVERED:
                    item.transition_to(OrderItem.Status.DELIVERED)
                    OrderEventService.emit(
                        session,
                        order_id=order.id,
                        order_item_id=item.id,
                        event_type=OrderEventType.ITEM_DELIVERED,
                        actor_type=ActorType.RIDER,
                        actor_id=user_id,
                    )
                if item.delivered_at is None:
                    item.delivered_at = datetime.utcnow()

            run_order.pod_status = DeliveryRunOrderPodStatus.DELIVERED
            run_order.delivered_at = datetime.utcnow()

            run_completed = False
            run = session.query(DeliveryRun).filter_by(id=run_id).first()
            if run and run.status == DeliveryRunStatus.DELIVERY_IN_PROGRESS:
                remaining = (
                    session.query(DeliveryRunOrder)
                    .filter(
                        DeliveryRunOrder.delivery_run_id == run_id,
                        DeliveryRunOrder.pod_status
                        != DeliveryRunOrderPodStatus.DELIVERED,
                    )
                    .count()
                )
                if remaining == 0:
                    run.transition_to(DeliveryRunStatus.COMPLETED)
                    run_completed = True

        OrderService.update_order_status(order_id, OrderStatus.DELIVERED)

        return {
            "status": "success",
            "message": "Order marked as delivered",
            "run_completed": run_completed,
        }
