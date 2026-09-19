"""Where a shared-delivery saving goes back to, and who decides.

ADR-002 rejected crediting a wallet *instead of* refunding a card: "you saved
N200, here is store credit" is a lock-in dressed as a saving. What it left
open was the buyer choosing, with the cash refund as default. That is what
this covers -- the choice is read, never made on their behalf, and the
promise attached to choosing the wallet ("withdraw whenever you want") is
actually kept.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import ValidationError
from app.payments.services import PaymentService
from app.users.models import RefundPreference
from app.wallet.services import MIN_WITHDRAWAL_AMOUNT, WalletService

ORDER = "ORD_1"
SAVING_MINOR = 20_000  # N200.00, the shape of a real batch saving


def _route(preference, *, wallet_raises=False, refund_ok=True):
    """Run return_to_buyer against a buyer with this stored preference."""
    row = ("USR_1", preference) if preference else None
    scope = MagicMock()
    scope.__enter__.return_value.query.return_value.join.return_value.filter.return_value.first.return_value = (  # noqa: E501
        row
    )
    credit = MagicMock(
        side_effect=RuntimeError("paystack down") if wallet_raises else None
    )
    with patch("app.payments.services.read_scope", return_value=scope), patch.object(
        WalletService, "credit", credit
    ), patch.object(
        PaymentService, "refund_to_source", return_value=refund_ok
    ) as refund:
        destination = PaymentService.return_to_buyer(
            ORDER, SAVING_MINOR, "Shared delivery came out cheaper than quoted"
        )
    return destination, credit, refund


def test_the_card_is_the_default():
    """Nobody's money becomes store credit because this shipped."""
    destination, credit, refund = _route(RefundPreference.CARD.value)
    assert destination == "card"
    credit.assert_not_called()
    refund.assert_called_once()


def test_a_buyer_who_asked_for_the_wallet_gets_the_wallet():
    destination, credit, refund = _route(RefundPreference.WALLET.value)
    assert destination == "wallet"
    refund.assert_not_called()
    assert credit.call_args.args[1] == Decimal("200.00")  # kobo -> naira


def test_the_wallet_credit_cannot_be_paid_twice():
    """Settlement is retryable; the buyer is not paid per attempt."""
    _, credit, _ = _route(RefundPreference.WALLET.value)
    assert credit.call_args.kwargs["idempotency_key"] == f"delivery-saving:{ORDER}"


def test_a_buyer_with_no_row_falls_back_to_the_card():
    destination, credit, _ = _route(None)
    assert destination == "card"
    credit.assert_not_called()


def test_a_failed_wallet_credit_still_pays_the_buyer():
    """The preference is about which is nicer, not about whether they get
    their money."""
    destination, _, refund = _route(RefundPreference.WALLET.value, wallet_raises=True)
    assert destination == "card"
    refund.assert_called_once()


def test_nothing_owed_means_nothing_sent():
    with patch.object(PaymentService, "refund_to_source") as refund:
        assert PaymentService.return_to_buyer(ORDER, 0, "x") == ""
        refund.assert_not_called()


def test_a_refund_that_could_not_be_sent_reports_nothing():
    destination, _, _ = _route(RefundPreference.CARD.value, refund_ok=False)
    assert destination == ""


# --- the promise that makes the wallet option honest ------------------------


def _withdraw(amount, balance):
    """request_withdrawal against a wallet holding `balance`."""
    account = MagicMock(available_balance=Decimal(balance), currency="NGN")
    session = MagicMock()
    scope = MagicMock()
    scope.__enter__.return_value = session
    with patch("app.wallet.services.session_scope", return_value=scope), patch.object(
        WalletService, "_get_or_create_account", return_value=account
    ), patch.object(WalletService, "debit"), patch(
        "app.wallet.tasks.process_withdrawal"
    ):
        return WalletService.request_withdrawal(
            "USR_1",
            {
                "amount": amount,
                "bank_code": "000",
                "account_number": "0000000000",
                "account_name": "Fake Buyer",
            },
        )


def test_a_batch_saving_can_actually_be_withdrawn():
    """The whole point. A N200 saving against a N1,000 floor would have been
    stuck until the buyer accumulated five more of them -- which is the
    lock-in ADR-002 refused, just wearing a different hat."""
    _withdraw(Decimal("200.00"), balance="200.00")


def test_a_small_balance_must_be_taken_out_whole():
    """Not a naira at a time: each transfer costs Markt a fee."""
    with pytest.raises(ValidationError):
        _withdraw(Decimal("50.00"), balance="200.00")


def test_the_floor_still_applies_to_a_large_balance():
    with pytest.raises(ValidationError) as excinfo:
        _withdraw(Decimal("500.00"), balance="50000.00")
    assert str(MIN_WITHDRAWAL_AMOUNT) in excinfo.value.message


def test_a_normal_withdrawal_is_unaffected():
    _withdraw(MIN_WITHDRAWAL_AMOUNT, balance="50000.00")


def test_you_still_cannot_withdraw_what_is_not_there():
    with pytest.raises(ValidationError) as excinfo:
        _withdraw(Decimal("5000.00"), balance="200.00")
    assert "insufficient" in excinfo.value.message.lower()
