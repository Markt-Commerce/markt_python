"""Unit tests for wallet service helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import ValidationError
from app.wallet.models import WalletReferenceType
from app.wallet.services import DEFAULT_COMMISSION_RATE, WalletService


def test_settle_order_item_calculates_net_after_commission():
    item = SimpleNamespace(
        id=42,
        price=10000.0,
        quantity=2,
        seller=SimpleNamespace(user_id="USR_SELLER1"),
    )
    gross = item.price * item.quantity
    expected_net = round(gross * (1 - DEFAULT_COMMISSION_RATE), 2)

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
