"""Celery tasks for payment-first checkout lifecycle maintenance (14.3:
payment/escrow reconciliation)."""

import logging
from datetime import datetime, timedelta

from main.workers import celery_app
from app.libs.session import session_scope
from app.libs.worker_log import record_worker_run
from app.payments.models import Payment, PaymentStatus

logger = logging.getLogger(__name__)

# How long a payment-first checkout (PaymentService.initialize_checkout_payment)
# can sit at PENDING before it's considered abandoned -- buyer closed the
# Paystack tab, network dropped, etc. Slightly longer than
# InventoryService.RESERVATION_TTL_MINUTES (10) so by the time this runs,
# the reservation(s) backing it have usually already lapsed on their own;
# this task is the administrative cleanup of the orphaned Payment row
# itself, plus a defensive backstop release for anything that's somehow
# still held.
CHECKOUT_PAYMENT_ABANDON_MINUTES = 15


@celery_app.task(
    name="app.payments.tasks.expire_abandoned_checkout_payments", queue="default"
)
def expire_abandoned_checkout_payments():
    """A payment-first checkout that never completes leaves its Payment
    stuck at PENDING forever -- nothing else ever cleans it up. Marks it
    FAILED past the abandonment window and releases whatever reservations
    are still active.

    Deliberately does NOT prevent a late webhook from later rescuing this
    payment -- Payment.FAILED -> COMPLETED is allowed by design (see that
    transition's own comment on the model). If that happens after this
    task has already released the reservation,
    PaymentService.complete_checkout_payment's own reconciliation handles
    it (refunds the specific unsecured item rather than pretending it's
    fulfillable)."""
    with record_worker_run(
        "app.payments.tasks.expire_abandoned_checkout_payments"
    ) as run:
        cutoff = datetime.utcnow() - timedelta(minutes=CHECKOUT_PAYMENT_ABANDON_MINUTES)
        expired_count = 0
        reservation_ids_to_release = []

        with session_scope() as session:
            stale_payments = (
                session.query(Payment)
                .filter(
                    Payment.status == PaymentStatus.PENDING,
                    Payment.order_id.is_(None),
                    Payment.pending_checkout_data.isnot(None),
                    Payment.created_at < cutoff,
                )
                .all()
            )

            for payment in stale_payments:
                payment.transition_to(PaymentStatus.FAILED)
                snapshot = payment.pending_checkout_data or {}
                for item in snapshot.get("items", []):
                    reservation_id = item.get("reservation_id")
                    if reservation_id:
                        reservation_ids_to_release.append(reservation_id)
                expired_count += 1

        if reservation_ids_to_release:
            from app.inventory.services import InventoryService

            InventoryService.release_reservations(reservation_ids_to_release)

        logger.info(
            "Expired %s abandoned checkout payment(s), released %s reservation(s)",
            expired_count,
            len(reservation_ids_to_release),
        )
        run.result = {"expired": expired_count}
        return run.result
