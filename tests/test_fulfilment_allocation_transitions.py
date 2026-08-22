"""Unit tests for FulfilmentAllocation.transition_to, the single source of
truth for seller accept/decline/timeout state changes (12.1-12.2)."""

import pytest

from app.fulfilment.models import FulfilmentAllocation, FulfilmentAllocationStatus


def _allocation(status):
    allocation = FulfilmentAllocation()
    allocation.status = status
    return allocation


@pytest.mark.parametrize(
    "start,target",
    [
        (
            FulfilmentAllocationStatus.AWAITING_SELLER,
            FulfilmentAllocationStatus.ACCEPTED,
        ),
        (
            FulfilmentAllocationStatus.AWAITING_SELLER,
            FulfilmentAllocationStatus.DECLINED,
        ),
        (
            FulfilmentAllocationStatus.AWAITING_SELLER,
            FulfilmentAllocationStatus.TIMEOUT,
        ),
        (FulfilmentAllocationStatus.DECLINED, FulfilmentAllocationStatus.REROUTING),
        (FulfilmentAllocationStatus.TIMEOUT, FulfilmentAllocationStatus.REROUTING),
        (FulfilmentAllocationStatus.REROUTING, FulfilmentAllocationStatus.ACCEPTED),
        (FulfilmentAllocationStatus.REROUTING, FulfilmentAllocationStatus.UNFULFILLED),
        (FulfilmentAllocationStatus.ACCEPTED, FulfilmentAllocationStatus.PREPARING),
    ],
)
def test_legal_transitions_apply(start, target):
    allocation = _allocation(start)
    allocation.transition_to(target)
    assert allocation.status == target


@pytest.mark.parametrize(
    "start,target",
    [
        (
            FulfilmentAllocationStatus.AWAITING_SELLER,
            FulfilmentAllocationStatus.PREPARING,
        ),
        (FulfilmentAllocationStatus.DECLINED, FulfilmentAllocationStatus.ACCEPTED),
        (FulfilmentAllocationStatus.TIMEOUT, FulfilmentAllocationStatus.ACCEPTED),
        (
            FulfilmentAllocationStatus.PREPARING,
            FulfilmentAllocationStatus.AWAITING_SELLER,
        ),
        (
            FulfilmentAllocationStatus.UNFULFILLED,
            FulfilmentAllocationStatus.REROUTING,
        ),
        (
            FulfilmentAllocationStatus.ACCEPTED,
            FulfilmentAllocationStatus.AWAITING_SELLER,
        ),
    ],
)
def test_illegal_transitions_raise(start, target):
    allocation = _allocation(start)
    with pytest.raises(ValueError):
        allocation.transition_to(target)
    assert allocation.status == start
