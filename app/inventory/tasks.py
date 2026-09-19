"""Celery tasks for inventory reservation lifecycle maintenance."""

import logging
from datetime import datetime

from main.workers import celery_app
from app.libs.session import session_scope
from app.libs.worker_log import record_worker_run
from app.inventory.confidence import InventoryConfidenceService
from app.inventory.models import InventoryReservation
from app.products.models import Product, ProductStatus

logger = logging.getLogger(__name__)

# Reservations that are still TTL-bound (not yet CONFIRMED into an order,
# which is indefinite until CONSUMED/RELEASED -- see 8.1).
TTL_BOUND_STATUSES = (
    InventoryReservation.Status.REQUESTED,
    InventoryReservation.Status.HELD,
)


@celery_app.task(name="app.inventory.tasks.expire_stale_reservations", queue="default")
def expire_stale_reservations():
    """Move reservations past their TTL to EXPIRED, releasing the stock
    they were holding (8.1) so it counts as available again."""
    with record_worker_run("app.inventory.tasks.expire_stale_reservations") as run:
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
        run.result = {"expired": expired_count}
        return run.result


@celery_app.task(
    name="app.inventory.tasks.recompute_confidence_scores", queue="default"
)
def recompute_confidence_scores():
    """Recompute Inventory Confidence (8.3) for every active product.
    Scheduled rather than computed on read, per the checklist -- the score
    only needs to be roughly fresh (recency decays over days, not minutes)."""
    with session_scope() as session:
        product_ids = [
            row[0]
            for row in session.query(Product.id)
            .filter(Product.status == ProductStatus.ACTIVE)
            .all()
        ]

    recomputed = 0
    failed = 0
    for product_id in product_ids:
        try:
            InventoryConfidenceService.calculate_score(product_id)
            recomputed += 1
        except Exception:
            failed += 1
            logger.exception(
                "Failed to recompute confidence score for product %s", product_id
            )

    logger.info(
        "Recomputed confidence scores for %s products (%s failed)",
        recomputed,
        failed,
    )
    return {"recomputed": recomputed, "failed": failed}
