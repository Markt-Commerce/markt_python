"""Tests for the settlement-hold payout worker (Phase 0: 12h after POD
before a seller is eligible for payout)."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.wallet.tasks import settle_eligible_order_items


@patch("app.wallet.services.WalletService.settle_order_item")
@patch("app.wallet.tasks.session_scope")
def test_settle_eligible_order_items_settles_and_marks_settled(
    mock_session_scope, mock_settle
):
    item = SimpleNamespace(id=1, settled_at=None)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [item]
    mock_session_scope.return_value.__enter__.return_value = session

    result = settle_eligible_order_items()

    assert result == {"settled": 1, "failed": 0}
    mock_settle.assert_called_once_with(item)
    assert item.settled_at is not None


@patch("app.wallet.services.WalletService.settle_order_item")
@patch("app.wallet.tasks.session_scope")
def test_settle_eligible_order_items_no_op_when_none_eligible(
    mock_session_scope, mock_settle
):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    mock_session_scope.return_value.__enter__.return_value = session

    result = settle_eligible_order_items()

    assert result == {"settled": 0, "failed": 0}
    mock_settle.assert_not_called()


@patch("app.wallet.services.WalletService.settle_order_item")
@patch("app.wallet.tasks.session_scope")
def test_settle_eligible_order_items_counts_failures_without_aborting(
    mock_session_scope, mock_settle
):
    item_a = SimpleNamespace(id=1, settled_at=None)
    item_b = SimpleNamespace(id=2, settled_at=None)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [
        item_a,
        item_b,
    ]
    mock_session_scope.return_value.__enter__.return_value = session
    mock_settle.side_effect = [Exception("boom"), None]

    result = settle_eligible_order_items()

    assert result == {"settled": 1, "failed": 1}
    assert item_a.settled_at is None
    assert item_b.settled_at is not None
