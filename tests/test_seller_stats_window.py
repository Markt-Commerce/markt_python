"""Seller dashboard stats expose a trailing 30-day window (#7).

GET /orders/seller/stats used to report lifetime totals plus a 30-day
earnings sum, but no 30-day *order count* -- so the dashboard could show a
lifetime number but not whether the shop is trending up or going quiet. The
stats now carry orders_last_30d alongside the lifetime total, and label the
window so the client needn't hard-code "30 days".

Follows the house style of mocking session_scope rather than standing up a
DB; this pins the response contract and the window constant."""

from unittest.mock import MagicMock, patch

from app.orders.services import SellerOrderService


def test_window_constant_is_30_days():
    assert SellerOrderService.STATS_WINDOW_DAYS == 30


@patch("app.orders.services.session_scope")
def test_stats_expose_trailing_window_count_and_label(mock_scope):
    # A chainable mock session: query/join/filter all return the mock, and the
    # terminal count()/scalar() return numbers so the dict assembles.
    session = MagicMock()
    chain = session.query.return_value
    chain.join.return_value = chain
    chain.filter.return_value = chain
    chain.count.return_value = 0
    chain.scalar.return_value = 0
    mock_scope.return_value.__enter__.return_value = session

    stats = SellerOrderService.get_seller_order_stats("SELL_1")

    # Lifetime totals still present (unchanged contract)...
    assert "total_orders" in stats
    assert "pending_orders" in stats
    assert "monthly_earnings" in stats
    # ...plus the new trailing-window trend count and its label (#7).
    assert "orders_last_30d" in stats
    assert stats["stats_window_days"] == 30
