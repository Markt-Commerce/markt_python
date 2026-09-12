"""Unit tests for OrderItem.transition_to, the single source of truth for
item status changes shared by the seller-reported and rider-POD paths."""

import pytest

from app.orders.models import OrderItem


def _item(status):
    item = OrderItem()
    item.status = status
    return item


@pytest.mark.parametrize(
    "start,target",
    [
        (OrderItem.Status.PENDING, OrderItem.Status.PROCESSING),
        (OrderItem.Status.PENDING, OrderItem.Status.CANCELLED),
        (OrderItem.Status.PROCESSING, OrderItem.Status.SHIPPED),
        (OrderItem.Status.PROCESSING, OrderItem.Status.DELIVERED),
        (OrderItem.Status.PROCESSING, OrderItem.Status.CANCELLED),
        (OrderItem.Status.SHIPPED, OrderItem.Status.DELIVERED),
    ],
)
def test_legal_transitions_apply(start, target):
    item = _item(start)
    item.transition_to(target)
    assert item.status == target


@pytest.mark.parametrize(
    "start,target",
    [
        (OrderItem.Status.PENDING, OrderItem.Status.SHIPPED),
        (OrderItem.Status.PENDING, OrderItem.Status.DELIVERED),
        (OrderItem.Status.SHIPPED, OrderItem.Status.PROCESSING),
        (OrderItem.Status.DELIVERED, OrderItem.Status.PROCESSING),
        (OrderItem.Status.DELIVERED, OrderItem.Status.SHIPPED),
        (OrderItem.Status.CANCELLED, OrderItem.Status.PROCESSING),
        (OrderItem.Status.CANCELLED, OrderItem.Status.DELIVERED),
    ],
)
def test_illegal_transitions_raise(start, target):
    item = _item(start)
    with pytest.raises(ValueError):
        item.transition_to(target)
    assert item.status == start
