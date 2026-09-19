"""Celery tasks for delivery-run batching lifecycle (10.1-10.4)."""

import logging

from main.workers import celery_app
from app.libs.worker_log import record_worker_run

logger = logging.getLogger(__name__)


@celery_app.task(name="app.deliveries.tasks.attach_eligible_orders", queue="default")
def attach_eligible_orders():
    """10.1: attach every fully-routed-and-confirmed order not yet in a
    run to the current open run for its market/area."""
    with record_worker_run("app.deliveries.tasks.attach_eligible_orders") as run:
        from app.deliveries.runs import DeliveryRunService

        result = DeliveryRunService.attach_eligible_orders()
        logger.info(
            "Attached %s order(s) to delivery runs (%s skipped)",
            result["attached"],
            result["skipped_unresolved"],
        )
        run.result = result
        return result


@celery_app.task(name="app.deliveries.tasks.close_runs_past_cutoff", queue="default")
def close_runs_past_cutoff():
    """10.2/10.3: close OPEN runs past their cutoff into PLANNING (priced),
    or CANCELLED if nothing joined (or nothing survived the wait-deadline
    fallback -- see DeliveryRunService.close_runs_past_cutoff)."""
    with record_worker_run("app.deliveries.tasks.close_runs_past_cutoff") as run:
        from app.deliveries.runs import DeliveryRunService

        result = DeliveryRunService.close_runs_past_cutoff()
        logger.info(
            "Closed %s delivery run(s) into planning (%s cancelled empty, "
            "%s free-cancelled on fallback)",
            result["closed"],
            result["cancelled_empty"],
            result["free_cancellations"],
        )
        run.result = result
        return result


@celery_app.task(name="app.deliveries.tasks.notify_thin_volume_orders", queue="default")
def notify_thin_volume_orders():
    """10.3: notify buyers on a still-thin OPEN run of the wait-vs-pay-now
    choice."""
    with record_worker_run("app.deliveries.tasks.notify_thin_volume_orders") as run:
        from app.deliveries.runs import DeliveryRunService

        result = DeliveryRunService.notify_thin_volume_orders()
        logger.info("Notified %s order(s) of thin delivery volume", result["notified"])
        run.result = result
        return result


@celery_app.task(name="app.deliveries.tasks.sweep_delivery_offers", queue="default")
def sweep_delivery_offers():
    """Release lapsed holds, and chase orders nobody has taken.

    This is what makes the countdown safe. The hold an offer puts on an
    order has an expiry, and nothing on the rider's phone is trusted to
    release it -- a backgrounded app, a dead battery or a ride through a
    basement must not be able to park an order indefinitely. So the expiry
    is enforced here, on a schedule, whether or not anyone comes back.

    It also chases: an order still unclaimed well after it went out gets
    re-alerted on a wider radius. An order sitting in a list nobody is
    refreshing is exactly how one gets forgotten in an area that had riders
    in it the whole time.
    """
    with record_worker_run("app.deliveries.tasks.sweep_delivery_offers") as run:
        from app.deliveries.offers import sweep

        result = sweep()
        logger.info(
            "Offer sweep: %s lapsed, %s re-alerted, %s escalated",
            result["lapsed"],
            result["realerted"],
            result["escalated"],
        )
        run.result = result
        return result
