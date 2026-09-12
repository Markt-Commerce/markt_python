"""Unit tests for Payment.transition_to, the single source of truth for
payment status changes shared by the webhook, callback, and refund paths."""

from unittest.mock import MagicMock, patch

import pytest

from app.payments.models import Payment, PaymentStatus
from app.payments.services import PaymentService


def _payment(status):
    payment = Payment()
    payment.status = status
    return payment


@pytest.mark.parametrize(
    "start,target",
    [
        (PaymentStatus.PENDING, PaymentStatus.COMPLETED),
        (PaymentStatus.PENDING, PaymentStatus.FAILED),
        (PaymentStatus.FAILED, PaymentStatus.COMPLETED),
        (PaymentStatus.COMPLETED, PaymentStatus.REFUNDED),
    ],
)
def test_legal_transitions_apply(start, target):
    payment = _payment(start)
    payment.transition_to(target)
    assert payment.status == target


@pytest.mark.parametrize(
    "start,target",
    [
        (PaymentStatus.COMPLETED, PaymentStatus.FAILED),
        (PaymentStatus.COMPLETED, PaymentStatus.PENDING),
        (PaymentStatus.REFUNDED, PaymentStatus.COMPLETED),
        (PaymentStatus.REFUNDED, PaymentStatus.PENDING),
        (PaymentStatus.FAILED, PaymentStatus.PENDING),
    ],
)
def test_illegal_transitions_raise(start, target):
    payment = _payment(start)
    with pytest.raises(ValueError):
        payment.transition_to(target)
    assert payment.status == start


def test_late_failed_webhook_cannot_undo_a_completed_payment():
    """A captured payment must never be flipped to failed by a late/duplicate
    webhook -- this is the money-integrity invariant this guard exists for."""
    payment = _payment(PaymentStatus.COMPLETED)

    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = payment

    with patch("app.payments.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = PaymentService._handle_failed_charge(
            {"reference": "PAY_1", "status": "failed"}
        )

    assert result is False
    assert payment.status == PaymentStatus.COMPLETED


def test_duplicate_failed_webhook_is_a_no_op():
    payment = _payment(PaymentStatus.FAILED)

    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = payment

    with patch("app.payments.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = PaymentService._handle_failed_charge(
            {"reference": "PAY_1", "status": "failed"}
        )

    assert result is True
    assert payment.status == PaymentStatus.FAILED
