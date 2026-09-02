"""Unit tests for wallet service helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import ValidationError
from app.libs.money import to_money
from app.wallet.models import WalletReferenceType
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
