"""Tests for Phase 3 marketplace payment features."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import ValidationError
from app.orders.models import OrderReturnStatus, OrderStatus
from app.orders.services import OrderService, RETURNABLE_ORDER_STATUSES
from app.payments.services import PaymentService
from app.wallet.models import TopUpStatus, WalletReferenceType
from app.wallet.services import WalletService


def test_returnable_order_statuses():
    assert OrderStatus.SHIPPED in RETURNABLE_ORDER_STATUSES
    assert OrderStatus.DELIVERED in RETURNABLE_ORDER_STATUSES
    assert OrderStatus.PENDING_PAYMENT not in RETURNABLE_ORDER_STATUSES


@patch("app.wallet.services.WalletService.credit")
def test_approve_return_credits_buyer_wallet(mock_credit):
    order = SimpleNamespace(
        id="ORD_RET001",
        total=8000.0,
        buyer=SimpleNamespace(user_id="USR_BUYER1"),
        items=[SimpleNamespace(seller_id=7, status=SimpleNamespace(value="delivered"))],
        payments=[SimpleNamespace(status=SimpleNamespace(value="completed"))],
    )
    order_return = SimpleNamespace(
        id="RET_TEST01",
        status=OrderReturnStatus.REQUESTED,
        refund_amount=8000.0,
        order=order,
        seller_notes=None,
    )

    session = MagicMock()
    session.query.return_value.options.return_value.get.return_value = order_return

    with patch("app.orders.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        from app.payments.models import PaymentStatus

        for payment in order.payments:
            payment.status = PaymentStatus.COMPLETED
        from app.orders.models import OrderItem

        order.items[0].status = OrderItem.Status.DELIVERED
        OrderService.approve_return("RET_TEST01", seller_id=7)

    mock_credit.assert_called_once()
    assert mock_credit.call_args.kwargs["idempotency_key"] == "return-refund:RET_TEST01"


@patch("app.wallet.services.WalletService.credit")
def test_complete_topup_is_idempotent(mock_credit):
    topup = SimpleNamespace(
        id="TOP_ABC123",
        user_id="USR_1",
        amount=5000.0,
        currency="NGN",
        status=TopUpStatus.PENDING,
    )

    session = MagicMock()
    session.query.return_value.get.return_value = topup

    with patch("app.wallet.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        assert WalletService.complete_topup("TOP_TOP_ABC123") is True

    mock_credit.assert_called_once()
    assert mock_credit.call_args[0][2] == WalletReferenceType.WALLET_TOPUP


@patch.object(WalletService, "credit")
def test_settle_order_item_skips_when_paystack_split_used(mock_credit):
    item = SimpleNamespace(
        id=99,
        order_id="ORD_SPLIT1",
        price=1000.0,
        quantity=1,
        seller=SimpleNamespace(user_id="USR_SELLER"),
    )
    order = SimpleNamespace(paystack_split_used=True)

    session = MagicMock()
    session.query.return_value.get.return_value = order

    with patch("app.wallet.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = WalletService.settle_order_item(item)

    assert result is None
    mock_credit.assert_not_called()


@patch("app.payments.services.PaymentService.complete_payment")
@patch("app.wallet.services.WalletService.complete_topup")
def test_webhook_routes_topup_references(mock_topup, mock_complete):
    mock_topup.return_value = True
    data = {"reference": "TOP_123", "metadata": {"type": "wallet_topup"}}
    assert PaymentService._handle_successful_charge(data) is True
    mock_topup.assert_called_once()
    mock_complete.assert_not_called()


@patch("app.wallet.paystack_subaccounts.PaystackSubaccountClient.create_subaccount")
def test_register_seller_payout_account(mock_create):
    mock_create.return_value = {"subaccount_code": "ACCT_sub123"}
    seller = SimpleNamespace(
        id=5,
        shop_name="Ada Shop",
        paystack_subaccount_code=None,
        payout_bank_code=None,
        payout_account_number=None,
        payout_account_name=None,
    )

    session = MagicMock()
    session.query.return_value.get.return_value = seller

    with patch("app.wallet.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = WalletService.register_seller_payout_account(
            5,
            bank_code="058",
            account_number="0123456789",
            account_name="Ada Lovelace",
        )

    assert result["subaccount_code"] == "ACCT_sub123"
    mock_create.assert_called_once()


def test_initialize_topup_rejects_small_amount():
    with pytest.raises(ValidationError):
        WalletService.initialize_topup("USR_1", 50.0)


def test_resolve_subaccount_split_single_seller():
    seller = SimpleNamespace(seller_id=1, paystack_subaccount_code="ACCT_abc")
    item = SimpleNamespace(seller_id=1, seller=seller)
    order = SimpleNamespace(items=[item])

    split = PaymentService._resolve_subaccount_split(order)
    assert split == {"subaccount_code": "ACCT_abc"}


def test_resolve_subaccount_split_multi_seller_returns_none():
    order = SimpleNamespace(
        items=[
            SimpleNamespace(seller_id=1, seller=None),
            SimpleNamespace(seller_id=2, seller=None),
        ]
    )
    assert PaymentService._resolve_subaccount_split(order) is None
