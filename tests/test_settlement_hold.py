"""Tests for the settlement-hold payout worker (Phase 0: 12h after POD
before a seller is eligible for payout)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.wallet.tasks import settle_eligible_order_items


def _session_yielding_ids(ids):
    """The task selects ids only, so the query chain ends in rows of tuples."""
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [
        (i,) for i in ids
    ]
    return session


@patch("app.wallet.services.WalletService.settle_order_item_by_id")
@patch("app.wallet.tasks.session_scope")
def test_settle_eligible_order_items_settles_each_eligible_item(
    mock_session_scope, mock_settle
):
    mock_session_scope.return_value.__enter__.return_value = _session_yielding_ids([1])
    mock_settle.return_value = SimpleNamespace(id=99)  # a WalletEntry

    result = settle_eligible_order_items()

    assert result == {"settled": 1, "failed": 0}
    mock_settle.assert_called_once_with(1)


@patch("app.wallet.services.WalletService.settle_order_item_by_id")
@patch("app.wallet.tasks.session_scope")
def test_settle_eligible_order_items_no_op_when_none_eligible(
    mock_session_scope, mock_settle
):
    mock_session_scope.return_value.__enter__.return_value = _session_yielding_ids([])

    result = settle_eligible_order_items()

    assert result == {"settled": 0, "failed": 0}
    mock_settle.assert_not_called()


@patch("app.wallet.services.WalletService.settle_order_item_by_id")
@patch("app.wallet.tasks.session_scope")
def test_settle_eligible_order_items_counts_failures_without_aborting(
    mock_session_scope, mock_settle
):
    mock_session_scope.return_value.__enter__.return_value = _session_yielding_ids(
        [1, 2]
    )
    mock_settle.side_effect = [Exception("boom"), SimpleNamespace(id=99)]

    result = settle_eligible_order_items()

    assert result == {"settled": 1, "failed": 1}
    assert mock_settle.call_count == 2


@patch("app.wallet.services.WalletService.settle_order_item_by_id")
@patch("app.wallet.tasks.session_scope")
def test_already_settled_item_is_not_counted(mock_session_scope, mock_settle):
    """settle_order_item_by_id returns None when the item was already settled
    (e.g. by a concurrent run between the select and the credit). That must not
    inflate the settled count."""
    mock_session_scope.return_value.__enter__.return_value = _session_yielding_ids([1])
    mock_settle.return_value = None

    result = settle_eligible_order_items()

    assert result == {"settled": 0, "failed": 0}


@patch("app.wallet.services.WalletService.settle_order_item_by_id")
@patch("app.wallet.tasks.session_scope")
def test_settlement_does_not_hold_a_session_open_across_credits(
    mock_session_scope, mock_settle
):
    """The regression this refactor exists for.

    The old task held one session_scope open across the whole batch and called
    into WalletService inside it. Because session_scope hands out the same
    scoped session, the credit's commit also committed every settled_at written
    so far -- a crash mid-batch left a partially committed batch.

    So: the task must open exactly one scope (the id select) and every credit
    must happen after it has closed.
    """
    mock_session_scope.return_value.__enter__.return_value = _session_yielding_ids(
        [1, 2, 3]
    )
    mock_settle.return_value = SimpleNamespace(id=99)

    settle_eligible_order_items()

    assert mock_session_scope.call_count == 1, (
        "task should open one scope for the id select; per-item transactions "
        "belong to settle_order_item_by_id"
    )
    # Every settlement ran after that scope exited.
    assert mock_session_scope.return_value.__exit__.call_count == 1
    assert mock_settle.call_count == 3
