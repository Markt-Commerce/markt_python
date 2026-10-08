"""Unit tests for DeliveryRun.transition_to, the single source of truth
for run-lifecycle state changes (10.2, reconciled with 10.7)."""

import pytest

from app.deliveries.models import DeliveryRun, DeliveryRunStatus


def _run(status):
    run = DeliveryRun()
    run.status = status
    return run


@pytest.mark.parametrize(
    "start,target",
    [
        (DeliveryRunStatus.OPEN, DeliveryRunStatus.CUTOFF_REACHED),
        (DeliveryRunStatus.OPEN, DeliveryRunStatus.CANCELLED),
        (DeliveryRunStatus.CUTOFF_REACHED, DeliveryRunStatus.PLANNING),
        (DeliveryRunStatus.CUTOFF_REACHED, DeliveryRunStatus.CANCELLED),
        (DeliveryRunStatus.PLANNING, DeliveryRunStatus.RIDER_ASSIGNMENT),
        (DeliveryRunStatus.PLANNING, DeliveryRunStatus.CANCELLED),
        (DeliveryRunStatus.RIDER_ASSIGNMENT, DeliveryRunStatus.RIDER_ACCEPTED),
        (DeliveryRunStatus.RIDER_ASSIGNMENT, DeliveryRunStatus.CANCELLED),
        (DeliveryRunStatus.RIDER_ACCEPTED, DeliveryRunStatus.PICKUP_IN_PROGRESS),
        (DeliveryRunStatus.RIDER_ACCEPTED, DeliveryRunStatus.CANCELLED),
        (DeliveryRunStatus.RIDER_ACCEPTED, DeliveryRunStatus.RIDER_FAILED),
        (DeliveryRunStatus.PICKUP_IN_PROGRESS, DeliveryRunStatus.DELIVERY_IN_PROGRESS),
        (DeliveryRunStatus.PICKUP_IN_PROGRESS, DeliveryRunStatus.RIDER_FAILED),
        (DeliveryRunStatus.DELIVERY_IN_PROGRESS, DeliveryRunStatus.COMPLETED),
        (
            DeliveryRunStatus.DELIVERY_IN_PROGRESS,
            DeliveryRunStatus.PARTIALLY_COMPLETED,
        ),
        (DeliveryRunStatus.DELIVERY_IN_PROGRESS, DeliveryRunStatus.RIDER_FAILED),
        # 10.7: "a failed run triggers reassignment where possible."
        (DeliveryRunStatus.RIDER_FAILED, DeliveryRunStatus.RIDER_ASSIGNMENT),
        (DeliveryRunStatus.RIDER_FAILED, DeliveryRunStatus.CANCELLED),
    ],
)
def test_legal_transitions_apply(start, target):
    run = _run(start)
    run.transition_to(target)
    assert run.status == target


@pytest.mark.parametrize(
    "start,target",
    [
        (DeliveryRunStatus.OPEN, DeliveryRunStatus.PLANNING),
        (DeliveryRunStatus.OPEN, DeliveryRunStatus.COMPLETED),
        (DeliveryRunStatus.CUTOFF_REACHED, DeliveryRunStatus.OPEN),
        (DeliveryRunStatus.PLANNING, DeliveryRunStatus.RIDER_ACCEPTED),
        (DeliveryRunStatus.RIDER_ASSIGNMENT, DeliveryRunStatus.PICKUP_IN_PROGRESS),
        (DeliveryRunStatus.COMPLETED, DeliveryRunStatus.CANCELLED),
        (DeliveryRunStatus.CANCELLED, DeliveryRunStatus.OPEN),
        (DeliveryRunStatus.PARTIALLY_COMPLETED, DeliveryRunStatus.COMPLETED),
    ],
)
def test_illegal_transitions_raise(start, target):
    run = _run(start)
    with pytest.raises(ValueError):
        run.transition_to(target)
    assert run.status == start
