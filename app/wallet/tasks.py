"""Celery tasks for wallet operations."""

import logging

from main.workers import celery_app

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
