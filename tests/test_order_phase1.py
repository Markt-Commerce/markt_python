"""Tests for Phase 1 order cancellation and tracking rules."""

from app.orders.models import OrderStatus
from app.orders.services import BUYER_CANCELLABLE_STATUSES


def test_buyer_cancellable_statuses_include_pending_payment():
    assert OrderStatus.PENDING_PAYMENT in BUYER_CANCELLABLE_STATUSES
    assert OrderStatus.READY_FOR_DELIVERY in BUYER_CANCELLABLE_STATUSES


def test_buyer_cannot_cancel_shipped_or_delivered():
    assert OrderStatus.SHIPPED not in BUYER_CANCELLABLE_STATUSES
    assert OrderStatus.DELIVERED not in BUYER_CANCELLABLE_STATUSES
    assert OrderStatus.CANCELLED not in BUYER_CANCELLABLE_STATUSES
