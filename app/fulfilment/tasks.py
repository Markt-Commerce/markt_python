"""Celery tasks for seller fulfilment lifecycle maintenance."""

import logging

from main.workers import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.fulfilment.tasks.expire_stale_allocations", queue="default")
def expire_stale_allocations():
    """Move AWAITING_SELLER allocations past their response deadline to
    TIMEOUT -> REROUTING (§12.2)."""
    from app.fulfilment.services import FulfilmentService

    result = FulfilmentService.expire_stale_allocations()
    logger.info("Timed out %s stale fulfilment allocation(s)", result["timed_out"])
    return result
