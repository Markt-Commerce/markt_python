"""Business metrics & dashboards (15). Read-only aggregation over
existing tables plus the Phase 8 worker run log -- no new
instrumentation, no new tables.

Two genuine gaps, flagged rather than guessed at: "delivery delays" has
no data to compute from (no promised-delivery-time concept exists
anywhere in this codebase -- same blocker Phase 12's "material delivery
delay" notification is stuck on) and is reported as such, not silently
omitted. "Missed pickups" has no directly-tracked analog either; the
closest real signal already tracked is a seller missing their response
window (FulfilmentAllocationStatus.TIMEOUT), reported under its own
honest name rather than mislabeled as rider-pickup lateness.
"""

import json
import logging
from datetime import datetime, timedelta

from app.deliveries.models import DeliveryRun, DeliveryRunStatus
from app.fulfilment.models import FulfilmentAllocation, FulfilmentAllocationStatus
from app.inventory.models import InventoryReservation
from app.libs.session import session_scope
from app.libs.worker_log import WORKER_LOG_FILENAME
from app.orders.events import OrderEvent, OrderEventType
from app.payments.models import Payment, PaymentStatus
from main.config import settings

logger = logging.getLogger(__name__)

# 7.1/Phase 6: these three ITEM_UNFULFILLED reasons represent the
# rerouting engine genuinely exhausting its search -- distinct from
# seller_only_preference (buyer opted out, never attempted) and
# original_product_missing (a data edge case), neither of which is a
# rerouting *failure* in any meaningful sense.
GENUINE_REROUTE_FAILURE_REASONS = {
    "deadline_or_retry_limit_reached",
    "no_eligible_candidates",
    "every_candidate_lost_stock_race",
}


class MetricsService:
    @staticmethod
    def _since(hours: int) -> datetime:
        return datetime.utcnow() - timedelta(hours=hours)

    @staticmethod
    def fulfilment_latency_seconds(session, since: datetime) -> dict:
        """Approximation, flagged: time from an item's most recent
        ITEM_ALLOCATED/ITEM_REROUTED event to its next ITEM_ACCEPTED
        event, per order item, averaged. Doesn't correlate a specific
        allocation attempt to its specific acceptance across multiple
        reroute rounds -- just "how long between the item last needing a
        seller and a seller actually committing," which is what
        fulfilment latency means for a buyer either way."""
        events = (
            session.query(OrderEvent)
            .filter(
                OrderEvent.event_type.in_(
                    [
                        OrderEventType.ITEM_ALLOCATED,
                        OrderEventType.ITEM_REROUTED,
                        OrderEventType.ITEM_ACCEPTED,
                    ]
                ),
                OrderEvent.created_at >= since,
                OrderEvent.order_item_id.isnot(None),
            )
            .order_by(OrderEvent.order_item_id, OrderEvent.created_at.asc())
            .all()
        )

        latencies = []
        pending_start = {}
        for event in events:
            item_id = event.order_item_id
            if event.event_type in (
                OrderEventType.ITEM_ALLOCATED,
                OrderEventType.ITEM_REROUTED,
            ):
                pending_start[item_id] = event.created_at
            elif event.event_type == OrderEventType.ITEM_ACCEPTED:
                start = pending_start.pop(item_id, None)
                if start:
                    latencies.append((event.created_at - start).total_seconds())

        if not latencies:
            return {
                "sample_size": 0,
                "average_seconds": None,
                "median_seconds": None,
            }

        latencies.sort()
        mid = len(latencies) // 2
        median = (
            latencies[mid]
            if len(latencies) % 2
            else (latencies[mid - 1] + latencies[mid]) / 2
        )
        return {
            "sample_size": len(latencies),
            "average_seconds": round(sum(latencies) / len(latencies), 1),
            "median_seconds": round(median, 1),
        }

    @staticmethod
    def rerouting_stats(session, since: datetime) -> dict:
        """Attempts succeeded = ITEM_REROUTED events (the engine actually
        found and locked a replacement). Attempts failed =
        ITEM_UNFULFILLED events whose reason means genuine exhaustion
        (see GENUINE_REROUTE_FAILURE_REASONS) -- not the
        seller_only_preference/original_product_missing short-circuits,
        which were never rerouting attempts to begin with."""
        rerouted = (
            session.query(OrderEvent)
            .filter(
                OrderEvent.event_type == OrderEventType.ITEM_REROUTED,
                OrderEvent.created_at >= since,
            )
            .count()
        )

        unfulfilled_events = (
            session.query(OrderEvent)
            .filter(
                OrderEvent.event_type == OrderEventType.ITEM_UNFULFILLED,
                OrderEvent.created_at >= since,
            )
            .all()
        )
        genuine_failures = sum(
            1
            for e in unfulfilled_events
            if (e.event_metadata or {}).get("reason") in GENUINE_REROUTE_FAILURE_REASONS
        )

        total = rerouted + genuine_failures
        success_rate = round(rerouted / total, 4) if total else None
        return {
            "attempts_succeeded": rerouted,
            "attempts_failed": genuine_failures,
            "success_rate": success_rate,
        }

    @staticmethod
    def reservation_failure_rate(session, since: datetime) -> dict:
        """EXPIRED (TTL lapsed, never confirmed) vs CONFIRMED (made it
        into an order) among reservations created in the window. RELEASED
        (explicit cleanup -- checkout abandoned, a later cart item failed)
        is excluded: that's not a reservation *failing*, it's the system
        correctly freeing stock nobody needed."""
        confirmed = (
            session.query(InventoryReservation)
            .filter(
                InventoryReservation.status == InventoryReservation.Status.CONFIRMED,
                InventoryReservation.created_at >= since,
            )
            .count()
        )
        expired = (
            session.query(InventoryReservation)
            .filter(
                InventoryReservation.status == InventoryReservation.Status.EXPIRED,
                InventoryReservation.created_at >= since,
            )
            .count()
        )
        total = confirmed + expired
        return {
            "confirmed": confirmed,
            "expired": expired,
            "failure_rate": round(expired / total, 4) if total else None,
        }

    @staticmethod
    def payment_failure_rate(session, since: datetime) -> dict:
        completed = (
            session.query(Payment)
            .filter(
                Payment.status == PaymentStatus.COMPLETED,
                Payment.created_at >= since,
            )
            .count()
        )
        failed = (
            session.query(Payment)
            .filter(
                Payment.status == PaymentStatus.FAILED,
                Payment.created_at >= since,
            )
            .count()
        )
        total = completed + failed
        return {
            "completed": completed,
            "failed": failed,
            "failure_rate": round(failed / total, 4) if total else None,
        }

    @staticmethod
    def substitution_rate(session, since: datetime) -> dict:
        """Of items actually delivered in the window, what fraction were
        ever rerouted (ITEM_REROUTED at some point in their history) --
        i.e. fulfilled by a different seller than the buyer originally
        chose."""
        delivered_events = (
            session.query(OrderEvent.order_item_id)
            .filter(
                OrderEvent.event_type == OrderEventType.ITEM_DELIVERED,
                OrderEvent.created_at >= since,
                OrderEvent.order_item_id.isnot(None),
            )
            .distinct()
            .all()
        )
        delivered_item_ids = {row[0] for row in delivered_events}
        if not delivered_item_ids:
            return {"delivered_items": 0, "substituted_items": 0, "rate": None}

        rerouted_ids = {
            row[0]
            for row in session.query(OrderEvent.order_item_id)
            .filter(
                OrderEvent.event_type == OrderEventType.ITEM_REROUTED,
                OrderEvent.order_item_id.in_(delivered_item_ids),
            )
            .distinct()
            .all()
        }
        substituted = len(delivered_item_ids & rerouted_ids)
        return {
            "delivered_items": len(delivered_item_ids),
            "substituted_items": substituted,
            "rate": round(substituted / len(delivered_item_ids), 4),
        }

    @staticmethod
    def missed_seller_response_windows(session, since: datetime) -> dict:
        """See this module's own docstring on why this stands in for the
        spec's "missed pickups" -- flagged, not a literal rider-pickup
        metric."""
        timed_out = (
            session.query(FulfilmentAllocation)
            .filter(
                FulfilmentAllocation.status == FulfilmentAllocationStatus.TIMEOUT,
                FulfilmentAllocation.updated_at >= since,
            )
            .count()
        )
        return {"seller_response_timeouts": timed_out}

    @staticmethod
    def stuck_orders(session) -> dict:
        """Live count, not windowed: allocations sitting at REROUTING (a
        state nothing times out on its own -- see
        FulfilmentService.recover_stuck_allocations) and runs sitting at
        RIDER_FAILED. Both should be near-zero at any healthy moment,
        since Phase 8/10's recovery workers sweep them every few minutes
        -- a nonzero count that persists across repeated checks is the
        real signal (that worker itself may be down), not a single
        snapshot."""
        stuck_allocations = (
            session.query(FulfilmentAllocation)
            .filter(FulfilmentAllocation.status == FulfilmentAllocationStatus.REROUTING)
            .count()
        )
        stuck_runs = (
            session.query(DeliveryRun)
            .filter(DeliveryRun.status == DeliveryRunStatus.RIDER_FAILED)
            .count()
        )
        return {
            "stuck_fulfilment_allocations": stuck_allocations,
            "stuck_delivery_runs": stuck_runs,
        }

    @staticmethod
    def worker_failures(since: datetime) -> dict:
        """Reads app.libs.worker_log's JSON-lines file directly -- Phase 8
        already writes one entry per scheduled worker run there
        (task/status/duration/error), so this is the one metric here
        needing zero new instrumentation."""
        path = settings.LOG_DIR / WORKER_LOG_FILENAME
        if not path.exists():
            return {"runs": 0, "failures": 0, "by_task": {}}

        runs = 0
        failures = 0
        by_task: dict = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    started_at = entry.get("started_at")
                    if not started_at:
                        continue
                    try:
                        ts = datetime.fromisoformat(started_at)
                    except ValueError:
                        continue
                    if ts.tzinfo is not None:
                        ts = ts.replace(tzinfo=None)
                    if ts < since:
                        continue
                    runs += 1
                    task = entry.get("task", "unknown")
                    task_stats = by_task.setdefault(task, {"runs": 0, "failures": 0})
                    task_stats["runs"] += 1
                    if entry.get("status") == "error":
                        failures += 1
                        task_stats["failures"] += 1
        except OSError:
            logger.exception("Failed to read worker run log for metrics")

        return {"runs": runs, "failures": failures, "by_task": by_task}

    @staticmethod
    def get_dashboard(since_hours: int = 24) -> dict:
        since = MetricsService._since(since_hours)
        with session_scope() as session:
            dashboard = {
                "window_hours": since_hours,
                "fulfilment_latency": MetricsService.fulfilment_latency_seconds(
                    session, since
                ),
                "rerouting": MetricsService.rerouting_stats(session, since),
                "reservations": MetricsService.reservation_failure_rate(session, since),
                "payments": MetricsService.payment_failure_rate(session, since),
                "substitution": MetricsService.substitution_rate(session, since),
                "missed_seller_response_windows": (
                    MetricsService.missed_seller_response_windows(session, since)
                ),
                "stuck_orders": MetricsService.stuck_orders(session),
            }
        dashboard["worker_failures"] = MetricsService.worker_failures(since)
        # 15/Phase 12: genuinely blocked, not silently omitted -- no
        # promised-delivery-time concept exists anywhere in this codebase
        # to compute "late" against (same gap "material delivery delay"
        # notifications are blocked on).
        dashboard["delivery_delays"] = None
        return dashboard
