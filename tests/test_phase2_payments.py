"""Tests for Phase 2 payment and wallet features."""

import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.payments.models import PaymentMethod
from app.payments.services import PaymentService
from app.wallet.models import WalletReferenceType
from app.wallet.services import WalletService


def test_verify_webhook_signature_uses_raw_body():
    secret = "sk_test_secret"
    body = b'{"event":"charge.success","data":{}}'
    signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()

    PaymentService.PAYSTACK_SECRET_KEY = secret
    assert PaymentService._verify_webhook_signature(signature, body) is True
    assert PaymentService._verify_webhook_signature(signature, b"{}") is False


def test_wallet_payment_method_enum_exists():
    assert PaymentMethod.WALLET.value == "wallet"


@patch("app.payments.services.PaymentService.complete_payment")
@patch("app.wallet.services.WalletService.pay_for_order")
def test_create_payment_wallet_debits_and_completes(mock_pay, mock_complete):
    mock_pay.return_value = MagicMock()
    mock_complete.return_value = True

    order = SimpleNamespace(
        id="ORD_TEST01",
        total=5000.0,
        subtotal=5000.0,
        buyer=SimpleNamespace(user_id="USR_BUYER1"),
    )
    payment = MagicMock()
    payment.id = "PAY_TEST01"

    session = MagicMock()
    session.query.return_value.options.return_value.get.return_value = order
    session.query.return_value.filter_by.return_value.first.return_value = None

    captured_payment = {}

    def assign_payment_id():
        if captured_payment.get("payment") is not None:
            captured_payment["payment"].id = "PAY_TEST01"

    session.flush.side_effect = assign_payment_id

    def capture_add(obj):
        captured_payment["payment"] = obj

    session.add.side_effect = capture_add

    with patch("app.payments.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with patch(
            "app.payments.services.PaymentService.get_payment", return_value=payment
        ):
            with patch("app.payments.services.PaymentService._cache_payment"):
                from app.orders.models import OrderStatus

                order.status = OrderStatus.PENDING_PAYMENT
                PaymentService.create_payment(
                    order_id="ORD_TEST01",
                    amount=None,
                    method=PaymentMethod.WALLET,
                )

    mock_pay.assert_called_once()
    mock_complete.assert_called_once_with(payment_id="PAY_TEST01")


@patch.object(WalletService, "debit")
def test_pay_for_order_uses_order_payment_reference(mock_debit):
    WalletService.pay_for_order("USR_1", "ORD_1", "PAY_1", 1000.0)
    mock_debit.assert_called_once()
    assert mock_debit.call_args[0][2] == WalletReferenceType.ORDER_PAYMENT
