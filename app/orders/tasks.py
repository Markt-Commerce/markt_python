"""Celery tasks for order lifecycle maintenance."""

import logging
from datetime import datetime, timedelta

from main.workers import celery_app
from app.libs.session import session_scope
from app.libs.worker_log import record_worker_run
from app.orders.models import Order, OrderStatus

logger = logging.getLogger(__name__)


@celery_app.task(name="app.orders.tasks.expire_unpaid_orders", queue="default")
def expire_unpaid_orders():
    """Cancel orders stuck in pending_payment beyond the configured TTL."""
    from main.config import settings

    with record_worker_run("app.orders.tasks.expire_unpaid_orders") as run:
        cutoff = datetime.utcnow() - timedelta(hours=settings.UNPAID_ORDER_EXPIRY_HOURS)
        expired_count = 0

        with session_scope() as session:
            stale_orders = (
                session.query(Order)
                .filter(
                    Order.status.in_(
                        [OrderStatus.PENDING_PAYMENT, OrderStatus.PENDING]
                    ),
                    Order.created_at < cutoff,
                )
                .all()
            )

            for order in stale_orders:
                order.status = OrderStatus.CANCELLED
                order.cancelled_at = datetime.utcnow()
                order.cancel_reason = "Automatically cancelled — payment not received"
                expired_count += 1

        logger.info(
            "Expired %s unpaid orders older than %sh",
            expired_count,
            settings.UNPAID_ORDER_EXPIRY_HOURS,
        )
        run.result = {"expired": expired_count}
        return run.result
