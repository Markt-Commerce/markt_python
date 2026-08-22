"""Unit tests for MarketService: seller-market assignment and the
geocode-distance verification check (§7.2, Phase 6 blocker resolution)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import NotFoundError, ValidationError
from app.markets.services import (
    MARKET_VERIFICATION_TOLERANCE_METERS,
    MarketService,
)
from app.users.models import MarketVerificationStatus


@patch("app.deliveries.services.DeliveryService.haversine_distance")
@patch("app.markets.services.geocode_address")
@patch("app.markets.services.session_scope")
def test_assign_seller_market_verifies_within_tolerance(
    mock_scope, mock_geocode, mock_distance
):
    seller = SimpleNamespace(id=1)
    market = SimpleNamespace(id=5, latitude=6.45, longitude=3.39)
    session = MagicMock()
    session.query.return_value.get.side_effect = [seller, market]
    mock_scope.return_value.__enter__.return_value = session
    mock_geocode.return_value = (6.451, 3.391)
    mock_distance.return_value = MARKET_VERIFICATION_TOLERANCE_METERS - 1

    result = MarketService.assign_seller_market(1, 5, {"street_address": "1 Rd"})

    assert result.market_id == 5
    assert result.market_verification_status == MarketVerificationStatus.VERIFIED


@patch("app.deliveries.services.DeliveryService.haversine_distance")
@patch("app.markets.services.geocode_address")
@patch("app.markets.services.session_scope")
def test_assign_seller_market_flags_outside_tolerance(
    mock_scope, mock_geocode, mock_distance
):
    seller = SimpleNamespace(id=1)
    market = SimpleNamespace(id=5, latitude=6.45, longitude=3.39)
    session = MagicMock()
    session.query.return_value.get.side_effect = [seller, market]
    mock_scope.return_value.__enter__.return_value = session
    mock_geocode.return_value = (7.5, 4.5)
    mock_distance.return_value = MARKET_VERIFICATION_TOLERANCE_METERS + 1

    result = MarketService.assign_seller_market(1, 5, {"street_address": "1 Rd"})

    assert result.market_verification_status == MarketVerificationStatus.FLAGGED


@patch("app.markets.services.geocode_address")
@patch("app.markets.services.session_scope")
def test_assign_seller_market_unverified_when_market_has_no_reference_location(
    mock_scope, mock_geocode
):
    seller = SimpleNamespace(id=1)
    market = SimpleNamespace(id=5, latitude=None, longitude=None)
    session = MagicMock()
    session.query.return_value.get.side_effect = [seller, market]
    mock_scope.return_value.__enter__.return_value = session
    mock_geocode.return_value = (6.45, 3.39)

    result = MarketService.assign_seller_market(1, 5, {"street_address": "1 Rd"})

    assert result.market_verification_status == MarketVerificationStatus.UNVERIFIED


@patch("app.markets.services.session_scope")
def test_assign_seller_market_raises_not_found_for_missing_seller(mock_scope):
    session = MagicMock()
    session.query.return_value.get.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(NotFoundError):
        MarketService.assign_seller_market(1, 5, {"street_address": "1 Rd"})


@patch("app.markets.services.session_scope")
def test_seed_market_rejects_invalid_latitude(mock_scope):
    with pytest.raises(ValidationError):
        MarketService.seed_market("Bodija Market", "bodija-market", latitude=200.0)


@patch("app.markets.services.session_scope")
def test_seed_market_returns_existing_when_slug_present(mock_scope):
    existing = SimpleNamespace(id=1, slug="bodija-market")
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = existing
    mock_scope.return_value.__enter__.return_value = session

    result = MarketService.seed_market("Bodija Market", "bodija-market")

    assert result is existing
    session.add.assert_not_called()
