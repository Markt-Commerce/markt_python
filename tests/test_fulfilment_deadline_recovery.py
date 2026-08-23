"""Tests for FulfilmentService.recover_stuck_allocations (14.3): the
backstop sweep for allocations stranded past their order item's
fulfilment deadline -- REROUTING (nothing else times it out on its own)
and any of the four attempt_reroute()-acceptable statuses whose
synchronous retry call never actually fired (e.g. a crash between the
two)."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.fulfilment.models import FulfilmentAllocation, FulfilmentAllocationStatus
from app.fulfilment.services import FulfilmentService


def _stuck_allocation(status, **overrides):
    defaults = dict(
        id=1,
        order_item_id=10,
        seller_id=7,
        reservation_id=None,
        created_at=datetime.utcnow() - timedelta(minutes=20),
    )
    defaults.update(overrides)
    a = SimpleNamespace(status=status, **defaults)
    a.transition_to = lambda new_status, _a=a: FulfilmentAllocation.transition_to(
        _a, new_status
    )
    return a


def _mock_session(
    distinct_pairs,
    history_by_item,
    allocations_by_id=None,
    order_items_by_id=None,
):
    session = MagicMock()

    def query_side_effect(model):
        if model is FulfilmentAllocation.order_item_id:
            m = MagicMock()
            m.filter.return_value.distinct.return_value.all.return_value = (
                distinct_pairs
            )
            return m

        name = getattr(model, "__name__", None)
        if name == "FulfilmentAllocation":
            m = MagicMock()

            def filter_by(**kwargs):
                oid = kwargs["order_item_id"]
                inner = MagicMock()
                inner.order_by.return_value.all.return_value = history_by_item.get(
                    oid, []
                )
                return inner

            m.filter_by.side_effect = filter_by
            m.get.side_effect = lambda aid: (allocations_by_id or {}).get(aid)
            return m

        if name == "OrderItem":
            m = MagicMock()
            m.get.side_effect = lambda oid: (order_items_by_id or {}).get(oid)
            return m

        return MagicMock()

    session.query.side_effect = query_side_effect
    return session


@patch("app.fulfilment.services.session_scope")
def test_recover_stuck_allocations_skips_items_not_past_deadline(mock_scope):
    allocation = _stuck_allocation(
        FulfilmentAllocationStatus.DECLINED,
        created_at=datetime.utcnow() - timedelta(minutes=2),
    )
    session = _mock_session([(10,)], {10: [allocation]})
    mock_scope.return_value.__enter__.return_value = session

    with patch(
        "app.fulfilment.rerouting.ReroutingService.attempt_reroute"
    ) as mock_attempt:
        result = FulfilmentService.recover_stuck_allocations()

    assert result == {"retried": 0, "resolved_stuck_rerouting": 0}
    mock_attempt.assert_not_called()


@patch("app.fulfilment.services.session_scope")
def test_recover_stuck_allocations_retries_declined_past_deadline(mock_scope):
    allocation = _stuck_allocation(FulfilmentAllocationStatus.DECLINED)
    session = _mock_session([(10,)], {10: [allocation]})
    mock_scope.return_value.__enter__.return_value = session

    with patch(
        "app.fulfilment.rerouting.ReroutingService.attempt_reroute"
    ) as mock_attempt:
        result = FulfilmentService.recover_stuck_allocations()

    assert result == {"retried": 1, "resolved_stuck_rerouting": 0}
    mock_attempt.assert_called_once_with(1)


@patch("app.fulfilment.services.session_scope")
def test_recover_stuck_allocations_ignores_superseded_history(mock_scope):
    """An item's earlier DECLINED row is normal permanent history once a
    later allocation (higher id) has moved the item on -- e.g. ACCEPTED --
    not a live problem the sweep should touch."""
    old = _stuck_allocation(FulfilmentAllocationStatus.DECLINED, id=1)
    newer = _stuck_allocation(FulfilmentAllocationStatus.ACCEPTED, id=2)
    session = _mock_session([(10,)], {10: [old, newer]})
    mock_scope.return_value.__enter__.return_value = session

    with patch(
        "app.fulfilment.rerouting.ReroutingService.attempt_reroute"
    ) as mock_attempt:
        result = FulfilmentService.recover_stuck_allocations()

    assert result == {"retried": 0, "resolved_stuck_rerouting": 0}
    mock_attempt.assert_not_called()


@patch("app.fulfilment.rerouting.escalate_unfulfilled_item")
@patch("app.fulfilment.services.session_scope")
def test_recover_stuck_allocations_resolves_stuck_rerouting(mock_scope, mock_escalate):
    """REROUTING has no deadline column/worker of its own -- the sweep
    resolves it straight to UNFULFILLED (attempt_reroute() itself won't
    accept REROUTING as a starting status, so calling it would no-op) and
    escalates, same outcome attempt_reroute() reaches internally."""
    allocation = _stuck_allocation(
        FulfilmentAllocationStatus.REROUTING, id=5, order_item_id=20
    )
    order_item = SimpleNamespace(id=20, order_id="ORD_1")

    session = _mock_session(
        [(20,)],
        {20: [allocation]},
        allocations_by_id={5: allocation},
        order_items_by_id={20: order_item},
    )
    mock_scope.return_value.__enter__.return_value = session

    with patch(
        "app.fulfilment.rerouting.ReroutingService.attempt_reroute"
    ) as mock_attempt:
        result = FulfilmentService.recover_stuck_allocations()

    assert result == {"retried": 0, "resolved_stuck_rerouting": 1}
    mock_attempt.assert_not_called()
    assert allocation.status == FulfilmentAllocationStatus.UNFULFILLED
    mock_escalate.assert_called_once_with(5)


@patch("app.fulfilment.rerouting.escalate_unfulfilled_item")
@patch("app.fulfilment.services.session_scope")
def test_recover_stuck_allocations_stuck_rerouting_no_op_if_already_resolved(
    mock_scope, mock_escalate
):
    """Guards against double-processing if the allocation moved on between
    the sweep query and this resolution step (e.g. a concurrent normal
    reroute attempt succeeded in the meantime)."""
    snapshot = _stuck_allocation(
        FulfilmentAllocationStatus.REROUTING, id=5, order_item_id=20
    )
    current = _stuck_allocation(
        FulfilmentAllocationStatus.ACCEPTED, id=5, order_item_id=20
    )

    session = _mock_session(
        [(20,)],
        {20: [snapshot]},
        allocations_by_id={5: current},
    )
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.recover_stuck_allocations()

    assert result == {"retried": 0, "resolved_stuck_rerouting": 0}
    mock_escalate.assert_not_called()
