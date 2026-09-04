"""Unit tests for MetricsService: business dashboards/observability (15,
Phase 12)."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.inventory.models import InventoryReservation
from app.metrics.services import MetricsService
from app.orders.events import OrderEvent, OrderEventType
from app.payments.models import Payment


def _event(order_item_id, event_type, created_at, metadata=None):
    return SimpleNamespace(
        order_item_id=order_item_id,
        event_type=event_type,
        created_at=created_at,
        event_metadata=metadata or {},
    )


# --- fulfilment_latency_seconds ---------------------------------------------


def test_fulfilment_latency_seconds_computes_average_and_median():
    t0 = datetime.utcnow()
    events = [
        _event(1, OrderEventType.ITEM_ALLOCATED, t0),
        _event(1, OrderEventType.ITEM_ACCEPTED, t0 + timedelta(seconds=10)),
        _event(2, OrderEventType.ITEM_REROUTED, t0),
        _event(2, OrderEventType.ITEM_ACCEPTED, t0 + timedelta(seconds=30)),
    ]
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
        events
    )

    result = MetricsService.fulfilment_latency_seconds(session, t0 - timedelta(days=1))

    assert result["sample_size"] == 2
    assert result["average_seconds"] == 20.0
    assert result["median_seconds"] == 20.0


def test_fulfilment_latency_seconds_empty():
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
        []
    )

    result = MetricsService.fulfilment_latency_seconds(session, datetime.utcnow())

    assert result == {
        "sample_size": 0,
        "average_seconds": None,
        "median_seconds": None,
    }


def test_fulfilment_latency_seconds_ignores_acceptance_with_no_prior_allocation():
    t0 = datetime.utcnow()
    events = [_event(1, OrderEventType.ITEM_ACCEPTED, t0)]
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
        events
    )

    result = MetricsService.fulfilment_latency_seconds(session, t0 - timedelta(days=1))

    assert result["sample_size"] == 0


# --- rerouting_stats ---------------------------------------------------------


def test_rerouting_stats_counts_success_and_genuine_failures():
    t0 = datetime.utcnow()
    unfulfilled = [
        _event(
            1, OrderEventType.ITEM_UNFULFILLED, t0, {"reason": "no_eligible_candidates"}
        ),
        _event(
            2, OrderEventType.ITEM_UNFULFILLED, t0, {"reason": "seller_only_preference"}
        ),
        _event(
            3,
            OrderEventType.ITEM_UNFULFILLED,
            t0,
            {"reason": "deadline_or_retry_limit_reached"},
        ),
    ]
    session = MagicMock()
    session.query.return_value.filter.return_value.count.return_value = 5
    session.query.return_value.filter.return_value.all.return_value = unfulfilled

    result = MetricsService.rerouting_stats(session, t0 - timedelta(days=1))

    assert result["attempts_succeeded"] == 5
    # 2 of 3 unfulfilled events are "genuine" reroute failures --
    # seller_only_preference was never an attempt to begin with.
    assert result["attempts_failed"] == 2
    assert result["success_rate"] == round(5 / 7, 4)


def test_rerouting_stats_success_rate_none_when_no_data():
    session = MagicMock()
    session.query.return_value.filter.return_value.count.return_value = 0
    session.query.return_value.filter.return_value.all.return_value = []

    result = MetricsService.rerouting_stats(session, datetime.utcnow())

    assert result["success_rate"] is None


# --- reservation_failure_rate ------------------------------------------------


def test_reservation_failure_rate():
    session = MagicMock()
    session.query.return_value.filter.return_value.count.side_effect = [8, 2]

    result = MetricsService.reservation_failure_rate(session, datetime.utcnow())

    assert result == {"confirmed": 8, "expired": 2, "failure_rate": 0.2}


def test_reservation_failure_rate_none_when_no_data():
    session = MagicMock()
    session.query.return_value.filter.return_value.count.side_effect = [0, 0]

    result = MetricsService.reservation_failure_rate(session, datetime.utcnow())

    assert result["failure_rate"] is None


# --- payment_failure_rate -----------------------------------------------------


def test_payment_failure_rate():
    session = MagicMock()
    session.query.return_value.filter.return_value.count.side_effect = [18, 2]

    result = MetricsService.payment_failure_rate(session, datetime.utcnow())

    assert result == {"completed": 18, "failed": 2, "failure_rate": 0.1}


# --- substitution_rate ---------------------------------------------------------


def test_substitution_rate_computes_correctly():
    session = MagicMock()
    session.query.return_value.filter.return_value.distinct.return_value.all.side_effect = [
        [(1,), (2,), (3,)],  # delivered
        [(2,)],  # rerouted, subset of delivered
    ]

    result = MetricsService.substitution_rate(session, datetime.utcnow())

    assert result == {
        "delivered_items": 3,
        "substituted_items": 1,
        "rate": round(1 / 3, 4),
    }


def test_substitution_rate_no_delivered_items():
    session = MagicMock()
    session.query.return_value.filter.return_value.distinct.return_value.all.return_value = (
        []
    )

    result = MetricsService.substitution_rate(session, datetime.utcnow())

    assert result == {"delivered_items": 0, "substituted_items": 0, "rate": None}


# --- missed_seller_response_windows / stuck_orders ----------------------------


def test_missed_seller_response_windows():
    session = MagicMock()
    session.query.return_value.filter.return_value.count.return_value = 4

    result = MetricsService.missed_seller_response_windows(session, datetime.utcnow())

    assert result == {"seller_response_timeouts": 4}


def test_stuck_orders():
    session = MagicMock()
    session.query.return_value.filter.return_value.count.side_effect = [3, 1]

    result = MetricsService.stuck_orders(session)

    assert result == {
        "stuck_fulfilment_allocations": 3,
        "stuck_delivery_runs": 1,
    }


# --- worker_failures -----------------------------------------------------------


def test_worker_failures_reads_log_file(tmp_path):
    now = datetime.utcnow()
    old = now - timedelta(days=2)
    log_file = tmp_path / "worker_runs.log"
    lines = [
        {"task": "a", "started_at": now.isoformat(), "status": "ok"},
        {"task": "a", "started_at": now.isoformat(), "status": "error"},
        {"task": "b", "started_at": now.isoformat(), "status": "error"},
        {
            "task": "a",
            "started_at": old.isoformat(),
            "status": "error",
        },  # out of window
        "not json",
    ]
    log_file.write_text(
        "\n".join(
            json.dumps(line) if isinstance(line, dict) else line for line in lines
        ),
        encoding="utf-8",
    )

    with patch("app.metrics.services.settings") as mock_settings:
        mock_settings.LOG_DIR = tmp_path
        result = MetricsService.worker_failures(now - timedelta(hours=1))

    assert result["runs"] == 3
    assert result["failures"] == 2
    assert result["by_task"]["a"] == {"runs": 2, "failures": 1}
    assert result["by_task"]["b"] == {"runs": 1, "failures": 1}


def test_worker_failures_missing_file(tmp_path):
    with patch("app.metrics.services.settings") as mock_settings:
        mock_settings.LOG_DIR = tmp_path
        result = MetricsService.worker_failures(datetime.utcnow())

    assert result == {"runs": 0, "failures": 0, "by_task": {}}


# --- get_dashboard ---------------------------------------------------------------


@patch("app.metrics.services.MetricsService.worker_failures")
@patch("app.metrics.services.MetricsService.stuck_orders")
@patch("app.metrics.services.MetricsService.missed_seller_response_windows")
@patch("app.metrics.services.MetricsService.substitution_rate")
@patch("app.metrics.services.MetricsService.payment_failure_rate")
@patch("app.metrics.services.MetricsService.reservation_failure_rate")
@patch("app.metrics.services.MetricsService.rerouting_stats")
@patch("app.metrics.services.MetricsService.fulfilment_latency_seconds")
@patch("app.metrics.services.session_scope")
def test_get_dashboard_combines_every_metric(
    mock_scope,
    mock_latency,
    mock_rerouting,
    mock_reservations,
    mock_payments,
    mock_substitution,
    mock_missed,
    mock_stuck,
    mock_worker,
):
    session = MagicMock()
    mock_scope.return_value.__enter__.return_value = session
    mock_latency.return_value = {"sample_size": 1}
    mock_rerouting.return_value = {"attempts_succeeded": 1}
    mock_reservations.return_value = {"confirmed": 1}
    mock_payments.return_value = {"completed": 1}
    mock_substitution.return_value = {"delivered_items": 1}
    mock_missed.return_value = {"seller_response_timeouts": 1}
    mock_stuck.return_value = {"stuck_fulfilment_allocations": 0}
    mock_worker.return_value = {"runs": 1}

    result = MetricsService.get_dashboard(since_hours=12)

    assert result["window_hours"] == 12
    assert result["fulfilment_latency"] == {"sample_size": 1}
    assert result["rerouting"] == {"attempts_succeeded": 1}
    assert result["reservations"] == {"confirmed": 1}
    assert result["payments"] == {"completed": 1}
    assert result["substitution"] == {"delivered_items": 1}
    assert result["missed_seller_response_windows"] == {"seller_response_timeouts": 1}
    assert result["stuck_orders"] == {"stuck_fulfilment_allocations": 0}
    assert result["worker_failures"] == {"runs": 1}
    # Genuinely blocked -- always null, never fabricated.
    assert result["delivery_delays"] is None
