"""Tests for the inventory reservation expiry task (§8.1: HELD -> EXPIRED)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.inventory.models import InventoryReservation
from app.inventory.tasks import expire_stale_reservations


def _reservation(status, expires_at):
    reservation = InventoryReservation()
    reservation.status = status
    reservation.expires_at = expires_at
    return reservation


@patch("app.inventory.tasks.session_scope")
def test_expire_stale_reservations_expires_held_past_ttl(mock_session_scope):
    stale = _reservation(
        InventoryReservation.Status.HELD, datetime.utcnow() - timedelta(minutes=1)
    )

    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [stale]
    mock_session_scope.return_value.__enter__.return_value = session

    result = expire_stale_reservations()

    assert result == {"expired": 1}
    assert stale.status == InventoryReservation.Status.EXPIRED


@patch("app.inventory.tasks.session_scope")
def test_expire_stale_reservations_expires_every_match(mock_session_scope):
    stale_held = _reservation(
        InventoryReservation.Status.HELD, datetime.utcnow() - timedelta(minutes=5)
    )
    stale_requested = _reservation(
        InventoryReservation.Status.REQUESTED, datetime.utcnow() - timedelta(minutes=5)
    )

    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [
        stale_held,
        stale_requested,
    ]
    mock_session_scope.return_value.__enter__.return_value = session

    result = expire_stale_reservations()

    assert result == {"expired": 2}
    assert stale_held.status == InventoryReservation.Status.EXPIRED
    assert stale_requested.status == InventoryReservation.Status.EXPIRED


@patch("app.inventory.tasks.session_scope")
def test_expire_stale_reservations_no_op_when_none_stale(mock_session_scope):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    mock_session_scope.return_value.__enter__.return_value = session

    result = expire_stale_reservations()

    assert result == {"expired": 0}
