"""Celery tasks for wallet operations."""

import logging
from datetime import datetime, timedelta

from main.workers import celery_app
from app.libs.session import session_scope

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.wallet.tasks.process_withdrawal",
    bind=True,
    max_retries=3,
    queue="default",
)
def process_withdrawal(self, withdrawal_id: str):
    """Process a pending withdrawal via Paystack Transfer API."""
    from app.wallet.services import WalletService

    try:
        WalletService.process_withdrawal(withdrawal_id)
    except Exception as exc:
        logger.error("Withdrawal task failed for %s: %s", withdrawal_id, exc)
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2**self.request.retries))
        raise


@celery_app.task(name="app.wallet.tasks.settle_eligible_order_items", queue="default")
def settle_eligible_order_items():
    """Pay out sellers for delivered items once the settlement hold (Phase
    0: 12h after POD) has elapsed. POD itself only records delivered_at
    (see DeliveryService.confirm_order_qr_code / OrderService.
    update_order_item_status) -- this task is the only thing that actually
    credits the seller's wallet.

    Selects ids in one short transaction, then settles each item in its own.
    Previously the whole loop ran inside a single session_scope and called
    into WalletService, which opens its own -- and since session_scope hands
    out the same scoped session, that inner commit also committed every
    settled_at written so far. A crash mid-batch left a partial commit that
    no longer looked like a batch. Selecting first also means a long payout
    run no longer holds a read transaction open across every credit.
    """
    from main.config import settings
    from app.orders.models import OrderItem
    from app.wallet.services import WalletService

    cutoff = datetime.utcnow() - timedelta(hours=settings.SETTLEMENT_HOLD_HOURS)
    settled_count = 0
    failed_count = 0

    with session_scope() as session:
        eligible_ids = [
            row[0]
            for row in session.query(OrderItem.id)
            .filter(
                OrderItem.status == OrderItem.Status.DELIVERED,
                OrderItem.delivered_at.isnot(None),
                OrderItem.delivered_at <= cutoff,
                OrderItem.settled_at.is_(None),
            )
            .all()
        ]

    for item_id in eligible_ids:
        try:
            # Re-checks eligibility under its own transaction, so an item
            # settled by a concurrent run between the select and here is a
            # no-op rather than a double payout.
            if WalletService.settle_order_item_by_id(item_id) is not None:
                settled_count += 1
        except Exception:
            failed_count += 1
            logger.exception("Failed to settle order item %s past its hold", item_id)

    logger.info(
        "Settled %s order item(s) past the %sh hold (%s failed)",
        settled_count,
        settings.SETTLEMENT_HOLD_HOURS,
        failed_count,
    )
    return {"settled": settled_count, "failed": failed_count}
