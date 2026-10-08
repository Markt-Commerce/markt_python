"""Tests for unpaid order expiry task."""

from unittest.mock import MagicMock, patch

from app.orders.models import OrderStatus
from app.orders.tasks import expire_unpaid_orders


@patch("app.orders.tasks.session_scope")
def test_expire_unpaid_orders_cancels_stale(mock_session_scope):
    stale_order = MagicMock()
    stale_order.status = OrderStatus.PENDING_PAYMENT

    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [stale_order]
    mock_session_scope.return_value.__enter__.return_value = session

    result = expire_unpaid_orders()
    assert result["expired"] == 1
    assert stale_order.status == OrderStatus.CANCELLED
    assert stale_order.cancel_reason is not None
