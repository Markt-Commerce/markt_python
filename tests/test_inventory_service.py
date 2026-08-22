"""Unit tests for InventoryService: available-quantity query and the
atomic reserve_stock endpoint (§8)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.inventory.confidence import ConfidenceBand, InventoryConfidenceService
from app.inventory.models import InventoryReservation
from app.inventory.services import InventoryService
from app.libs.errors import ConflictError, NotFoundError, ValidationError


def test_get_reported_quantity_uses_product_stock_when_no_variant():
    product = SimpleNamespace(stock=15)
    session = MagicMock()
    session.query.return_value.get.return_value = product

    assert InventoryService.get_reported_quantity(session, "PRD_1") == 15


def test_get_reported_quantity_uses_product_inventory_for_variant():
    inventory = SimpleNamespace(quantity=4)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = inventory

    assert InventoryService.get_reported_quantity(session, "PRD_1", variant_id=9) == 4


def test_get_reported_quantity_returns_zero_when_missing():
    session = MagicMock()
    session.query.return_value.get.return_value = None

    assert InventoryService.get_reported_quantity(session, "PRD_MISSING") == 0


def test_get_active_reserved_quantity_sums_non_terminal_reservations():
    session = MagicMock()
    session.query.return_value.filter.return_value.scalar.return_value = 6

    assert InventoryService.get_active_reserved_quantity(session, "PRD_1") == 6


def test_get_active_reserved_quantity_defaults_to_zero_when_none():
    session = MagicMock()
    session.query.return_value.filter.return_value.scalar.return_value = None

    assert InventoryService.get_active_reserved_quantity(session, "PRD_1") == 0


@patch.object(InventoryService, "get_active_reserved_quantity")
@patch.object(InventoryService, "get_reported_quantity")
def test_available_quantity_subtracts_active_reservations(mock_reported, mock_reserved):
    mock_reported.return_value = 10
    mock_reserved.return_value = 3

    with patch("app.inventory.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = MagicMock()
        result = InventoryService.get_available_quantity("PRD_1")

    assert result == 7


@patch.object(InventoryService, "get_active_reserved_quantity")
@patch.object(InventoryService, "get_reported_quantity")
def test_available_quantity_never_goes_negative(mock_reported, mock_reserved):
    mock_reported.return_value = 2
    mock_reserved.return_value = 5

    with patch("app.inventory.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = MagicMock()
        result = InventoryService.get_available_quantity("PRD_1")

    assert result == 0


def test_reserve_stock_rejects_non_positive_quantity():
    with pytest.raises(ValidationError):
        InventoryService.reserve_stock("PRD_1", buyer_id=1, quantity=0)


def test_reserve_stock_raises_not_found_when_product_missing():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.with_for_update.return_value.first.return_value = (
        None
    )

    with patch("app.inventory.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(NotFoundError):
            InventoryService.reserve_stock("PRD_MISSING", buyer_id=1, quantity=1)


@patch.object(InventoryService, "get_active_reserved_quantity")
def test_reserve_stock_raises_conflict_when_insufficient_available(mock_reserved):
    product = SimpleNamespace(id="PRD_1", stock=5)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.with_for_update.return_value.first.return_value = (
        product
    )
    mock_reserved.return_value = 4

    with patch("app.inventory.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ConflictError):
            InventoryService.reserve_stock("PRD_1", buyer_id=1, quantity=2)

    session.add.assert_not_called()


@patch.object(InventoryConfidenceService, "get_band_for_product")
@patch.object(InventoryService, "get_active_reserved_quantity")
def test_reserve_stock_locks_owner_row_and_creates_held_reservation(
    mock_reserved, mock_band
):
    product = SimpleNamespace(id="PRD_1", stock=5)
    session = MagicMock()
    query_mock = session.query.return_value
    query_mock.filter_by.return_value.with_for_update.return_value.first.return_value = (
        product
    )
    mock_reserved.return_value = 1
    mock_band.return_value = ConfidenceBand.HIGH

    with patch("app.inventory.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        reservation = InventoryService.reserve_stock("PRD_1", buyer_id=42, quantity=2)

    query_mock.filter_by.return_value.with_for_update.assert_called_once()
    assert reservation.status == InventoryReservation.Status.HELD
    assert reservation.needs_verification is False
    assert reservation.quantity == 2
    assert reservation.buyer_id == 42
    assert reservation.expires_at is not None
    session.add.assert_called_once_with(reservation)


@patch.object(InventoryConfidenceService, "get_band_for_product")
@patch.object(InventoryService, "get_active_reserved_quantity")
def test_reserve_stock_variant_path_uses_product_inventory(mock_reserved, mock_band):
    inventory = SimpleNamespace(id=1, quantity=5)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.with_for_update.return_value.first.return_value = (
        inventory
    )
    mock_reserved.return_value = 0
    mock_band.return_value = ConfidenceBand.HIGH

    with patch("app.inventory.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        reservation = InventoryService.reserve_stock(
            "PRD_1", buyer_id=1, quantity=3, variant_id=9
        )

    assert reservation.variant_id == 9
    assert reservation.status == InventoryReservation.Status.HELD


@patch.object(InventoryConfidenceService, "get_band_for_product")
@patch.object(InventoryService, "get_active_reserved_quantity")
def test_reserve_stock_medium_confidence_holds_but_flags_verification(
    mock_reserved, mock_band
):
    product = SimpleNamespace(id="PRD_1", stock=5)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.with_for_update.return_value.first.return_value = (
        product
    )
    mock_reserved.return_value = 0
    mock_band.return_value = ConfidenceBand.MEDIUM

    with patch("app.inventory.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        reservation = InventoryService.reserve_stock("PRD_1", buyer_id=1, quantity=1)

    assert reservation.status == InventoryReservation.Status.HELD
    assert reservation.needs_verification is True


@patch.object(InventoryConfidenceService, "get_band_for_product")
@patch.object(InventoryService, "get_active_reserved_quantity")
def test_reserve_stock_low_confidence_stays_requested_pending_seller_confirmation(
    mock_reserved, mock_band
):
    product = SimpleNamespace(id="PRD_1", stock=5)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.with_for_update.return_value.first.return_value = (
        product
    )
    mock_reserved.return_value = 0
    mock_band.return_value = ConfidenceBand.LOW

    with patch("app.inventory.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        reservation = InventoryService.reserve_stock("PRD_1", buyer_id=1, quantity=1)

    assert reservation.status == InventoryReservation.Status.REQUESTED
    assert reservation.needs_verification is False
