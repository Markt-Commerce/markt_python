"""Celery tasks for seller fulfilment lifecycle maintenance."""

import logging

from main.workers import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.fulfilment.tasks.expire_stale_allocations", queue="default")
def expire_stale_allocations():
    """Move AWAITING_SELLER allocations past their response deadline to
    TIMEOUT (§12.2). Stops there -- the reroute loop is what advances a
    TIMEOUT (or DECLINED) allocation to REROUTING once it actually picks
    the item up."""
    from app.fulfilment.services import FulfilmentService

    result = FulfilmentService.expire_stale_allocations()
    logger.info("Timed out %s stale fulfilment allocation(s)", result["timed_out"])
    return result


@celery_app.task(
    name="app.fulfilment.tasks.expire_stale_buyer_approvals", queue="default"
)
def expire_stale_buyer_approvals():
    """§9.1: move AWAITING_BUYER_APPROVAL allocations past their buyer
    response deadline to UNFULFILLED, refunding just that item -- no
    substitution retry (see FulfilmentService.expire_stale_buyer_approvals'
    own docstring for why this is deliberately unlike the seller-timeout
    task above)."""
    from app.fulfilment.services import FulfilmentService

    result = FulfilmentService.expire_stale_buyer_approvals()
    logger.info(
        "Timed out %s stale buyer-approval allocation(s) (§9.1)", result["timed_out"]
    )
    return result


@celery_app.task(
    name="app.fulfilment.tasks.recompute_seller_reliability_scores", queue="default"
)
def recompute_seller_reliability_scores():
    """Recompute Seller Reliability (§13.2) for every active seller.
    Scheduled rather than computed on read, same as Phase 3's inventory
    confidence recompute."""
    from app.fulfilment.reliability import SellerReliabilityService
    from app.libs.session import session_scope
    from app.users.models import Seller

    with session_scope() as session:
        seller_ids = [
            row[0] for row in session.query(Seller.id).filter_by(is_active=True).all()
        ]

    recomputed = 0
    failed = 0
    for seller_id in seller_ids:
        try:
            SellerReliabilityService.calculate_score(seller_id)
            recomputed += 1
        except Exception:
            failed += 1
            logger.exception(
                "Failed to recompute reliability score for seller %s", seller_id
            )

    logger.info(
        "Recomputed reliability scores for %s sellers (%s failed)",
        recomputed,
        failed,
    )
    return {"recomputed": recomputed, "failed": failed}
