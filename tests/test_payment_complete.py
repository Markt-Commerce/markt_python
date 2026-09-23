"""Unit tests for payment amount resolution and completion."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import ValidationError
from app.orders.models import OrderStatus
from app.payments.models import PaymentStatus
from app.payments.services import PaymentService


def test_resolve_order_payment_amount_uses_order_total():
    order = SimpleNamespace(total=11500.0, subtotal=10000.0)
    assert PaymentService._resolve_order_payment_amount(order, 11500.0) == 11500.0


def test_resolve_order_payment_amount_rejects_mismatch():
    order = SimpleNamespace(total=11500.0, subtotal=10000.0)
    with pytest.raises(ValidationError) as exc:
        PaymentService._resolve_order_payment_amount(order, 100.0)
    assert "does not match order total" in exc.value.message


def test_resolve_order_payment_amount_without_client_amount():
    order = SimpleNamespace(total=5000.0, subtotal=4500.0)
    assert PaymentService._resolve_order_payment_amount(order, None) == 5000.0


@patch("app.payments.services.PaymentService._emit_payment_confirmed")
@patch("app.payments.services.PaymentService._send_payment_notifications")
@patch("app.payments.services.PaymentService._invalidate_payment_cache")
@patch("app.products.services.ProductService.reduce_inventory_for_order")
@patch("app.payments.services.session_scope")
def test_complete_payment_is_idempotent(
    mock_session_scope,
    mock_reduce_inventory,
    mock_invalidate_cache,
    mock_notify,
    mock_emit,
):
    payment = MagicMock()
    payment.id = "PAY_TEST01"
    payment.status = PaymentStatus.COMPLETED
    payment.paid_at = None
    payment.gateway_response = {}
    payment.order_id = "ORD_TEST01"
    payment.amount = 1000.0
    payment.transaction_id = "ref-1"
    payment.method = MagicMock(value="card")
    payment.order = MagicMock(
        status=OrderStatus.READY_FOR_DELIVERY,
        order_number="ORD-1",
        buyer=MagicMock(user_id="USR_1"),
        items=[],
    )

    session = MagicMock()
    mock_session_scope.return_value.__enter__.return_value = session
    session.query.return_value.with_for_update.return_value.filter_by.return_value.first.return_value = (
        payment
    )

    assert PaymentService.complete_payment(payment_id="PAY_TEST01") is True
    mock_reduce_inventory.assert_not_called()
    mock_notify.assert_not_called()
    mock_emit.assert_not_called()
