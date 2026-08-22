"""Unit tests for the per-item refund primitive (§11.8) and the cumulative
escrow invariant it required (§9.1's ASK timeout is today's only caller,
via FulfilmentService.expire_stale_buyer_approvals)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import NotFoundError, ValidationError
from app.orders.models import OrderItem
from app.orders.services import OrderService
from app.payments.models import Payment, PaymentStatus


def _payment(status, amount=1000.0):
    p = SimpleNamespace(status=status, amount=amount)
    p.transition_to = lambda new_status, _p=p: Payment.transition_to(_p, new_status)
    return p


def _order_item(status=OrderItem.Status.PROCESSING, **overrides):
    defaults = dict(
        id=1,
        price=500.0,
        quantity=2,
        order=None,
    )
    defaults.update(overrides)
    item = SimpleNamespace(status=status, **defaults)
    item.transition_to = lambda new_status, _i=item: OrderItem.transition_to(
        _i, new_status
    )
    return item


@patch("app.wallet.services.WalletService.refund_order_item_to_wallet")
@patch("app.orders.services.session_scope")
def test_refund_unresolved_item_happy_path(mock_scope, mock_refund):
    payment = _payment(PaymentStatus.COMPLETED, amount=1000.0)
    order = SimpleNamespace(
        id="ORD_1",
        buyer=SimpleNamespace(user_id="USR_BUYER1"),
        payments=[payment],
        items=[],
    )
    order_item = _order_item(price=500.0, quantity=2, order=order)

    session = MagicMock()
    session.query.return_value.options.return_value.get.return_value = order_item
    # No prior refunds against this order.
    session.query.return_value.filter.return_value.scalar.return_value = 0.0
    mock_scope.return_value.__enter__.return_value = session

    OrderService.refund_unresolved_item(1, reason="test reason")

    assert order_item.status == OrderItem.Status.CANCELLED
    assert payment.status == PaymentStatus.PARTIALLY_REFUNDED
    mock_refund.assert_called_once_with("USR_BUYER1", 1, 1000.0, reason="test reason")


@patch("app.wallet.services.WalletService.refund_order_item_to_wallet")
@patch("app.orders.services.session_scope")
def test_refund_unresolved_item_is_idempotent(mock_scope, mock_refund):
    order_item = _order_item(status=OrderItem.Status.CANCELLED)

    session = MagicMock()
    session.query.return_value.options.return_value.get.return_value = order_item
    mock_scope.return_value.__enter__.return_value = session

    result = OrderService.refund_unresolved_item(1)

    assert result is None
    mock_refund.assert_not_called()


@patch("app.orders.services.session_scope")
def test_refund_unresolved_item_raises_not_found(mock_scope):
    session = MagicMock()
    session.query.return_value.options.return_value.get.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(NotFoundError):
        OrderService.refund_unresolved_item(1)


@patch("app.wallet.services.WalletService.refund_order_item_to_wallet")
@patch("app.orders.services.session_scope")
def test_refund_unresolved_item_rejects_refund_exceeding_captured(
    mock_scope, mock_refund
):
    payment = _payment(PaymentStatus.COMPLETED, amount=100.0)
    order = SimpleNamespace(
        id="ORD_1",
        buyer=SimpleNamespace(user_id="USR_BUYER1"),
        payments=[payment],
        items=[],
    )
    # Item alone is worth more than what was actually captured for the order.
    order_item = _order_item(price=500.0, quantity=2, order=order)

    session = MagicMock()
    session.query.return_value.options.return_value.get.return_value = order_item
    session.query.return_value.filter.return_value.scalar.return_value = 0.0
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ValidationError):
        OrderService.refund_unresolved_item(1)

    mock_refund.assert_not_called()


@patch("app.wallet.services.WalletService.refund_order_item_to_wallet")
@patch("app.orders.services.session_scope")
def test_refund_unresolved_item_accounts_for_prior_refunds(mock_scope, mock_refund):
    """The cumulative invariant: a second per-item refund against the same
    order must be rejected once prior refunds + this one would exceed what
    was actually captured, even though this refund alone would fit."""
    payment = _payment(PaymentStatus.PARTIALLY_REFUNDED, amount=1000.0)
    order = SimpleNamespace(
        id="ORD_1",
        buyer=SimpleNamespace(user_id="USR_BUYER1"),
        payments=[payment],
        items=[],
    )
    order_item = _order_item(price=500.0, quantity=1, order=order)

    session = MagicMock()
    session.query.return_value.options.return_value.get.return_value = order_item
    # 700 already refunded; this refund (500) would push total to 1200 > 1000 captured.
    session.query.return_value.filter.return_value.scalar.return_value = 700.0
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ValidationError):
        OrderService.refund_unresolved_item(1)

    mock_refund.assert_not_called()


@patch("app.wallet.services.WalletService.refund_order_to_wallet")
@patch("app.orders.services.ProductService.restore_inventory_for_order")
@patch("app.orders.services.session_scope")
def test_cancel_order_refunds_only_remaining_amount_after_prior_item_refund(
    mock_scope, mock_restore, mock_refund
):
    """cancel_order must not re-refund money already paid out by an
    earlier per-item refund (§9.1 ASK timeout, or any future partial
    refund) -- only the remainder still owed."""
    from app.orders.models import OrderStatus

    payment = _payment(PaymentStatus.PARTIALLY_REFUNDED, amount=1000.0)
    order = SimpleNamespace(
        id="ORD_1",
        buyer_id=42,
        status=OrderStatus.READY_FOR_DELIVERY,
        buyer=SimpleNamespace(user_id="USR_BUYER1"),
        payments=[payment],
        items=[_order_item(status=OrderItem.Status.PROCESSING, id=2, order=None)],
    )
    order.items[0].order = order

    session = MagicMock()
    session.query.return_value.options.return_value.get.return_value = order
    # 300 already refunded out of 1000 captured -- only 700 should go out now.
    session.query.return_value.filter.return_value.scalar.return_value = 300.0
    mock_scope.return_value.__enter__.return_value = session

    OrderService.cancel_order("ORD_1", buyer_id=42)

    mock_refund.assert_called_once_with("USR_BUYER1", "ORD_1", 700.0)
    assert payment.status == PaymentStatus.REFUNDED
