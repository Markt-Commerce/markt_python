"""Unit tests for wallet service helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import ValidationError
from app.libs.money import to_money
from app.wallet.models import TopUpStatus, WalletReferenceType
from app.wallet.services import DEFAULT_COMMISSION_RATE, WalletService


def test_settle_order_item_calculates_net_after_commission():
    item = SimpleNamespace(
        id=42,
        order_id="ORD_1",
        # Money is Decimal end to end now (NUMERIC(12,2) columns), so the
        # fixture uses the same type the ORM would hand back.
        price=to_money("10000.00"),
        quantity=2,
        seller=SimpleNamespace(user_id="USR_SELLER1"),
    )
    gross = item.price * item.quantity
    expected_net = to_money(gross * (1 - DEFAULT_COMMISSION_RATE))

    order = SimpleNamespace(paystack_split_used=False)
    session = MagicMock()
    session.query.return_value.get.return_value = order

    with patch("app.wallet.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with patch.object(WalletService, "credit") as mock_credit:
            mock_credit.return_value = MagicMock()
            WalletService.settle_order_item(item)
            mock_credit.assert_called_once()
            assert mock_credit.call_args[0][1] == expected_net


def test_credit_rejects_non_positive_amount():
    with pytest.raises(ValidationError) as exc:
        WalletService.credit(
            "USR_1",
            0,
            WalletReferenceType.ADJUSTMENT,
            "ref-1",
        )
    assert "positive" in exc.value.message


def test_credit_is_idempotent_for_repeated_key():
    """A second credit call with the same idempotency key must not double-pay."""
    existing_entry = SimpleNamespace(id=1)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = (
        existing_entry
    )

    with patch("app.wallet.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = WalletService.credit(
            "USR_1",
            500.0,
            WalletReferenceType.ORDER_REFUND,
            "ORD_1",
            idempotency_key="refund:order:ORD_1",
        )

    assert result is existing_entry
    session.add.assert_not_called()


def test_settle_order_item_rejects_invalid_commission_rate():
    """Commission rate must stay within [0, 1] so settlement can never exceed gross."""
    item = SimpleNamespace(
        id=42,
        order_id="ORD_1",
        price=10000.0,
        quantity=1,
        seller=SimpleNamespace(user_id="USR_SELLER1"),
    )
    order = SimpleNamespace(paystack_split_used=False)
    session = MagicMock()
    session.query.return_value.get.return_value = order

    with patch("app.wallet.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ValidationError):
            WalletService.settle_order_item(item, commission_rate=1.5)


# --- Paystack top-up verification -----------------------------------------
#
# complete_topup used to credit purely on being called with a reference, so a
# signed-but-mismatched charge.success event would move the exact amount the
# top-up row happened to claim. Paystack's guidance is to confirm data.status,
# data.amount and data.currency before giving value.


def _pending_topup(amount=5000.0, currency="NGN"):
    return SimpleNamespace(
        id="TOP_1",
        user_id="USR_1",
        amount=amount,
        currency=currency,
        status=TopUpStatus.PENDING,
        paystack_reference="TOP_TOP_1",
    )


def _topup_session(topup):
    session = MagicMock()
    session.query.return_value.get.return_value = topup
    session.query.return_value.filter_by.return_value.first.return_value = topup
    return session


@pytest.mark.parametrize(
    "gateway_response, reason",
    [
        ({"status": "failed", "amount": 500000, "currency": "NGN"}, "status"),
        ({"status": "success", "amount": 100, "currency": "NGN"}, "amount"),
        ({"status": "success", "amount": 500000, "currency": "USD"}, "currency"),
    ],
)
def test_complete_topup_refuses_mismatched_gateway_payload(gateway_response, reason):
    topup = _pending_topup()
    session = _topup_session(topup)

    with patch("app.wallet.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with patch.object(WalletService, "credit") as mock_credit:
            credited = WalletService.complete_topup("TOP_TOP_1", gateway_response)

    assert credited is False, f"should not credit on {reason} mismatch"
    mock_credit.assert_not_called()
    assert topup.status is TopUpStatus.PENDING


def test_complete_topup_credits_when_gateway_payload_matches():
    topup = _pending_topup()
    session = _topup_session(topup)

    with patch("app.wallet.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with patch.object(WalletService, "credit") as mock_credit:
            credited = WalletService.complete_topup(
                "TOP_TOP_1",
                {"status": "success", "amount": 500000, "currency": "NGN"},
            )

    assert credited is True
    mock_credit.assert_called_once()
    # Credited from the local record, keyed so webhook retries can't double-pay.
    assert mock_credit.call_args[0][1] == 5000.0
    assert mock_credit.call_args[1]["idempotency_key"] == "topup:TOP_1"
    assert topup.status is TopUpStatus.COMPLETED


def test_complete_topup_is_idempotent_once_completed():
    topup = _pending_topup()
    topup.status = TopUpStatus.COMPLETED
    session = _topup_session(topup)

    with patch("app.wallet.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with patch.object(WalletService, "credit") as mock_credit:
            credited = WalletService.complete_topup(
                "TOP_TOP_1",
                {"status": "success", "amount": 500000, "currency": "NGN"},
            )

    assert credited is True
    mock_credit.assert_not_called()


def test_balance_mutations_lock_the_wallet_row():
    """credit/debit must hold a row lock across the read-modify-write.

    Paystack retries a webhook every 3 minutes, so concurrent deliveries of the
    same event are routine; an unlocked balance update loses one of them.
    """
    session = MagicMock()
    # No existing entry for the idempotency key, so the write path is reached.
    session.query.return_value.filter_by.return_value.with_for_update.return_value.first.return_value = SimpleNamespace(  # noqa: E501
        # Decimal, matching what a NUMERIC(12,2) column hands back. A float
        # here raises on contact with the Decimal amount -- which is the money
        # refactor working as intended, not a regression.
        id=1,
        currency="NGN",
        available_balance=to_money("1000.00"),
    )
    session.query.return_value.filter_by.return_value.first.return_value = None

    with patch("app.wallet.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        WalletService.credit(
            "USR_1",
            250.0,
            WalletReferenceType.WALLET_TOPUP,
            "TOP_1",
            idempotency_key="topup:TOP_1",
        )

    session.query.return_value.filter_by.return_value.with_for_update.assert_called()
