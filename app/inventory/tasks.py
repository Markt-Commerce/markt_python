"""Celery tasks for inventory reservation lifecycle maintenance."""

import logging
from datetime import datetime

from main.workers import celery_app
from app.libs.session import session_scope
from app.inventory.models import InventoryReservation

logger = logging.getLogger(__name__)

# Reservations that are still TTL-bound (not yet CONFIRMED into an order,
# which is indefinite until CONSUMED/RELEASED -- see §8.1).
TTL_BOUND_STATUSES = (
    InventoryReservation.Status.REQUESTED,
    InventoryReservation.Status.HELD,
)


@celery_app.task(name="app.inventory.tasks.expire_stale_reservations", queue="default")
def expire_stale_reservations():
    """Move reservations past their TTL to EXPIRED, releasing the stock
    they were holding (§8.1) so it counts as available again."""
    now = datetime.utcnow()
    expired_count = 0

    with session_scope() as session:
        stale_reservations = (
            session.query(InventoryReservation)
            .filter(
                InventoryReservation.status.in_(TTL_BOUND_STATUSES),
                InventoryReservation.expires_at < now,
            )
            .all()
        )

        for reservation in stale_reservations:
            reservation.transition_to(InventoryReservation.Status.EXPIRED)
            expired_count += 1

    logger.info("Expired %s stale inventory reservations", expired_count)
    return {"expired": expired_count}
