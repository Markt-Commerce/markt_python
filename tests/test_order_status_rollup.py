"""Order-level status rolls up from its items (#5): an order is only as far
along as its least-advanced active item. CANCELLED items are excluded so one
declined item can't drag a mostly-shipped order backwards.

Pure-function tests on roll_up_order_status -- the mapping that
OrderService._recompute_order_status applies, and off the back of which
update_order_status notifies the buyer on SHIPPED (#4)."""

import pytest

from app.orders.models import OrderStatus, OrderItem
from app.orders.services import roll_up_order_status

S = OrderItem.Status


@pytest.mark.parametrize(
    "item_statuses,expected",
    [
        # Least-advanced active item wins.
        ([S.PENDING], OrderStatus.READY_FOR_DELIVERY),
        ([S.PENDING, S.PENDING], OrderStatus.READY_FOR_DELIVERY),
        # A paid-but-untouched item keeps the order at READY_FOR_DELIVERY even
        # while a sibling races ahead -- it must not claim PROCESSING/SHIPPED.
        ([S.PENDING, S.SHIPPED], OrderStatus.READY_FOR_DELIVERY),
        ([S.PENDING, S.PROCESSING, S.DELIVERED], OrderStatus.READY_FOR_DELIVERY),
        ([S.PROCESSING], OrderStatus.PROCESSING),
        ([S.PROCESSING, S.SHIPPED], OrderStatus.PROCESSING),
        ([S.PROCESSING, S.DELIVERED], OrderStatus.PROCESSING),
        ([S.SHIPPED], OrderStatus.SHIPPED),
        ([S.SHIPPED, S.SHIPPED], OrderStatus.SHIPPED),
        ([S.SHIPPED, S.DELIVERED], OrderStatus.SHIPPED),
        # Only when every item is in does the order read DELIVERED.
        ([S.DELIVERED], OrderStatus.DELIVERED),
        ([S.DELIVERED, S.DELIVERED], OrderStatus.DELIVERED),
    ],
)
def test_least_advanced_active_item_wins(item_statuses, expected):
    assert roll_up_order_status(item_statuses) == expected


@pytest.mark.parametrize(
    "item_statuses,expected",
    [
        # A declined item leaves the active set; the rest decide.
        ([S.CANCELLED, S.SHIPPED], OrderStatus.SHIPPED),
        ([S.CANCELLED, S.PROCESSING, S.SHIPPED], OrderStatus.PROCESSING),
        ([S.CANCELLED, S.PENDING, S.SHIPPED], OrderStatus.READY_FOR_DELIVERY),
        ([S.CANCELLED, S.DELIVERED], OrderStatus.DELIVERED),
    ],
)
def test_cancelled_items_are_excluded(item_statuses, expected):
    assert roll_up_order_status(item_statuses) == expected


@pytest.mark.parametrize(
    "item_statuses",
    [
        [],
        [S.CANCELLED],
        [S.CANCELLED, S.CANCELLED],
    ],
)
def test_no_active_items_rolls_up_to_nothing(item_statuses):
    # The cancellation/return paths own the terminal order status; the rollup
    # stays out of it rather than guessing CANCELLED.
    assert roll_up_order_status(item_statuses) is None
