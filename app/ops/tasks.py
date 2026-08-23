"""Generic stuck-order recovery worker (14.3): an independent, slower
backstop sweep across every spec-timed waiting state this codebase
tracks, re-running each already-idempotent recovery/expiry function
directly regardless of whether that state's own tight-interval Beat
schedule entry actually fired. "No worker is the sole owner of
progression" (14.3's own wording) -- if a specific worker's schedule
entry gets misconfigured or removed, its queue backs up, or it silently
stops firing, this sweep still catches whatever it would have.

Deliberately does NOT reimplement any recovery logic -- every function
called below already knows how to find its own overdue rows and advance
them safely, and is documented as safe to call more than once. This is
only a coordinator: it calls each task function directly (in-process,
synchronous -- not through the broker), isolates failures so one broken
sub-sweep can't stop the others, and lets each sub-call's own
`record_worker_run` (app.libs.worker_log) entry stand on its own in the
log, same as when the dedicated Beat entry runs it.

Covers every entry in 14.3's own worker list that has a concrete,
buildable implementation today: reservation-expiry, seller-timeout, 9.1
buyer-approval-timeout, fulfilment-deadline recovery, payment/escrow
reconciliation, and unpaid-order expiry (the old order-first flow's own
equivalent of payment reconciliation). Delivery-window close is NOT
included -- it needs `DeliveryRun` (Phase 9), which doesn't exist yet.
"""

import logging

from main.workers import celery_app
from app.libs.worker_log import record_worker_run

logger = logging.getLogger(__name__)


@celery_app.task(name="app.ops.tasks.recover_stuck_orders", queue="default")
def recover_stuck_orders():
    with record_worker_run("app.ops.tasks.recover_stuck_orders") as run:
        from app.fulfilment.tasks import (
            expire_stale_allocations,
            expire_stale_buyer_approvals,
            recover_stuck_fulfilment_allocations,
        )
        from app.inventory.tasks import expire_stale_reservations
        from app.orders.tasks import expire_unpaid_orders
        from app.payments.tasks import expire_abandoned_checkout_payments

        sub_sweeps = {
            "reservation_expiry": expire_stale_reservations,
            "seller_timeout": expire_stale_allocations,
            "buyer_approval_timeout": expire_stale_buyer_approvals,
            "fulfilment_deadline_recovery": recover_stuck_fulfilment_allocations,
            "payment_reconciliation": expire_abandoned_checkout_payments,
            "unpaid_order_expiry": expire_unpaid_orders,
        }

        summary = {}
        failures = 0
        for name, fn in sub_sweeps.items():
            try:
                summary[name] = fn()
            except Exception as exc:
                failures += 1
                summary[name] = {"error": str(exc)}
                logger.exception("Stuck-order recovery sub-sweep '%s' failed", name)

        logger.info(
            "Generic stuck-order recovery sweep complete: %s sub-sweep(s), %s failed",
            len(sub_sweeps),
            failures,
        )
        run.result = {"sub_sweeps": summary, "failures": failures}
        return run.result
