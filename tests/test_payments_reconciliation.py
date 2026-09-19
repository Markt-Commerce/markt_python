"""Unit tests for 14.3's payment/escrow reconciliation worker: cleaning
up abandoned payment-first checkouts that never completed."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.payments.models import Payment, PaymentStatus
from app.payments.tasks import expire_abandoned_checkout_payments


def _pending_payment(**overrides):
    defaults = dict(
        id="PAY_1",
        status=PaymentStatus.PENDING,
        order_id=None,
        pending_checkout_data={"items": [{"reservation_id": "RSV_1"}]},
    )
    defaults.update(overrides)
    p = SimpleNamespace(**defaults)
    p.transition_to = lambda new_status, _p=p: Payment.transition_to(_p, new_status)
    return p


@patch("app.inventory.services.InventoryService.release_reservations")
@patch("app.payments.tasks.session_scope")
def test_expire_abandoned_checkout_payments_fails_and_releases_reservations(
    mock_scope, mock_release
):
    payment = _pending_payment()
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [payment]
    mock_scope.return_value.__enter__.return_value = session

    result = expire_abandoned_checkout_payments()

    assert result == {"expired": 1}
    assert payment.status == PaymentStatus.FAILED
    mock_release.assert_called_once_with(["RSV_1"])


@patch("app.inventory.services.InventoryService.release_reservations")
@patch("app.payments.tasks.session_scope")
def test_expire_abandoned_checkout_payments_releases_every_item_reservation(
    mock_scope, mock_release
):
    payment = _pending_payment(
        pending_checkout_data={
            "items": [
                {"reservation_id": "RSV_1"},
                {"reservation_id": "RSV_2"},
            ]
        }
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [payment]
    mock_scope.return_value.__enter__.return_value = session

    expire_abandoned_checkout_payments()

    mock_release.assert_called_once_with(["RSV_1", "RSV_2"])


@patch("app.inventory.services.InventoryService.release_reservations")
@patch("app.payments.tasks.session_scope")
def test_expire_abandoned_checkout_payments_no_op_when_none_stale(
    mock_scope, mock_release
):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    mock_scope.return_value.__enter__.return_value = session

    result = expire_abandoned_checkout_payments()

    assert result == {"expired": 0}
    mock_release.assert_not_called()


@patch("app.payments.tasks.session_scope")
def test_expire_abandoned_checkout_payments_filters_pending_orderless_checkout_only(
    mock_scope,
):
    """The query itself is what scopes this to payment-first checkouts
    that never built an order -- an already-built order (order_id set) or
    an order-first flow payment (no pending_checkout_data) must never be
    touched by this worker."""
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    mock_scope.return_value.__enter__.return_value = session

    expire_abandoned_checkout_payments()

    filter_args = session.query.return_value.filter.call_args[0]
    filter_strs = [str(arg) for arg in filter_args]
    assert any("status" in s for s in filter_strs)
    assert any("order_id" in s for s in filter_strs)
    assert any("pending_checkout_data" in s for s in filter_strs)
    assert any("created_at" in s for s in filter_strs)
