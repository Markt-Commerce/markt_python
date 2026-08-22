"""Unit tests for InventoryReservation.transition_to, the single source of
truth for reservation status changes (§8.1)."""

import pytest

from app.inventory.models import InventoryReservation


def _reservation(status):
    reservation = InventoryReservation()
    reservation.status = status
    return reservation


@pytest.mark.parametrize(
    "start,target",
    [
        (InventoryReservation.Status.REQUESTED, InventoryReservation.Status.HELD),
        (InventoryReservation.Status.REQUESTED, InventoryReservation.Status.EXPIRED),
        (InventoryReservation.Status.REQUESTED, InventoryReservation.Status.RELEASED),
        (InventoryReservation.Status.HELD, InventoryReservation.Status.CONFIRMED),
        (InventoryReservation.Status.HELD, InventoryReservation.Status.EXPIRED),
        (InventoryReservation.Status.HELD, InventoryReservation.Status.RELEASED),
        (InventoryReservation.Status.CONFIRMED, InventoryReservation.Status.CONSUMED),
        (InventoryReservation.Status.CONFIRMED, InventoryReservation.Status.RELEASED),
    ],
)
def test_legal_transitions_apply(start, target):
    reservation = _reservation(start)
    reservation.transition_to(target)
    assert reservation.status == target


@pytest.mark.parametrize(
    "start,target",
    [
        (InventoryReservation.Status.REQUESTED, InventoryReservation.Status.CONFIRMED),
        (InventoryReservation.Status.REQUESTED, InventoryReservation.Status.CONSUMED),
        (InventoryReservation.Status.HELD, InventoryReservation.Status.CONSUMED),
        (InventoryReservation.Status.HELD, InventoryReservation.Status.REQUESTED),
        (InventoryReservation.Status.CONFIRMED, InventoryReservation.Status.HELD),
        (InventoryReservation.Status.CONFIRMED, InventoryReservation.Status.EXPIRED),
        (InventoryReservation.Status.CONSUMED, InventoryReservation.Status.RELEASED),
        (InventoryReservation.Status.EXPIRED, InventoryReservation.Status.HELD),
        (InventoryReservation.Status.RELEASED, InventoryReservation.Status.HELD),
    ],
)
def test_illegal_transitions_raise(start, target):
    reservation = _reservation(start)
    with pytest.raises(ValueError):
        reservation.transition_to(target)
    assert reservation.status == start
