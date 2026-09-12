"""Unit tests for MarketService: seller-market assignment and the
geocode-distance verification check (7.2, Phase 6 blocker resolution)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import NotFoundError, ValidationError
from app.markets.services import (
    AREA_RESOLUTION_TOLERANCE_METERS,
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


@patch("app.deliveries.services.DeliveryService.haversine_distance")
def test_resolve_area_for_coordinates_returns_nearest_within_tolerance(mock_distance):
    area_near = SimpleNamespace(id=1, latitude=6.45, longitude=3.39)
    area_far = SimpleNamespace(id=2, latitude=10.0, longitude=10.0)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [
        area_near,
        area_far,
    ]
    mock_distance.side_effect = [500, 50000]

    result = MarketService.resolve_area_for_coordinates(session, 6.451, 3.391)

    assert result is area_near


@patch("app.deliveries.services.DeliveryService.haversine_distance")
def test_resolve_area_for_coordinates_returns_none_outside_tolerance(mock_distance):
    area = SimpleNamespace(id=1, latitude=6.45, longitude=3.39)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [area]
    mock_distance.return_value = AREA_RESOLUTION_TOLERANCE_METERS + 1

    result = MarketService.resolve_area_for_coordinates(session, 6.451, 3.391)

    assert result is None


def test_resolve_area_for_coordinates_returns_none_for_missing_coordinates():
    session = MagicMock()

    assert MarketService.resolve_area_for_coordinates(session, None, 3.39) is None
    assert MarketService.resolve_area_for_coordinates(session, 6.45, None) is None
    session.query.assert_not_called()


def test_resolve_area_for_coordinates_returns_none_when_no_areas_have_location():
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []

    result = MarketService.resolve_area_for_coordinates(session, 6.45, 3.39)

    assert result is None


# ----------------------------------------------------------------------
# Market browsing (Phase 13 mobile): list_markets/get_market and the
# sellers/products/posts delegation to the owning services.
# ----------------------------------------------------------------------


@patch("app.markets.services.session_scope")
def test_list_markets_returns_active_markets_with_seller_counts(mock_scope):
    market_a = SimpleNamespace(
        id=1, name="Bodija", slug="bodija", latitude=1.0, longitude=2.0, is_active=True
    )
    market_b = SimpleNamespace(
        id=2, name="Sabo", slug="sabo", latitude=None, longitude=None, is_active=True
    )
    session = MagicMock()
    market_query = MagicMock()
    market_query.filter.return_value.order_by.return_value.all.return_value = [
        market_a,
        market_b,
    ]
    count_query = MagicMock()
    count_query.filter.return_value.group_by.return_value.all.return_value = [(1, 3)]
    session.query.side_effect = [market_query, count_query]
    mock_scope.return_value.__enter__.return_value = session

    result = MarketService.list_markets()

    assert result == [
        {
            "id": 1,
            "name": "Bodija",
            "slug": "bodija",
            "latitude": 1.0,
            "longitude": 2.0,
            "is_active": True,
            "seller_count": 3,
        },
        {
            "id": 2,
            "name": "Sabo",
            "slug": "sabo",
            "latitude": None,
            "longitude": None,
            "is_active": True,
            "seller_count": 0,
        },
    ]


@patch("app.markets.services.session_scope")
def test_list_markets_returns_empty_list_without_querying_counts(mock_scope):
    session = MagicMock()
    market_query = MagicMock()
    market_query.filter.return_value.order_by.return_value.all.return_value = []
    session.query.return_value = market_query
    mock_scope.return_value.__enter__.return_value = session

    result = MarketService.list_markets()

    assert result == []


@patch("app.markets.services.session_scope")
def test_get_market_returns_market_with_seller_count(mock_scope):
    market = SimpleNamespace(
        id=5, name="Bodija", slug="bodija", latitude=1.0, longitude=2.0, is_active=True
    )
    session = MagicMock()
    session.query.return_value.get.return_value = market
    session.query.return_value.filter.return_value.count.return_value = 7
    mock_scope.return_value.__enter__.return_value = session

    result = MarketService.get_market(5)

    assert result["seller_count"] == 7
    assert result["id"] == 5


@patch("app.markets.services.session_scope")
def test_get_market_raises_not_found(mock_scope):
    session = MagicMock()
    session.query.return_value.get.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(NotFoundError):
        MarketService.get_market(999)


@patch("app.users.services.ShopService.search_shops")
@patch("app.markets.services.session_scope")
def test_list_market_sellers_delegates_with_market_id(mock_scope, mock_search_shops):
    session = MagicMock()
    session.query.return_value.get.return_value = SimpleNamespace(id=5)
    mock_scope.return_value.__enter__.return_value = session
    mock_search_shops.return_value = {"shops": [], "pagination": {}}

    result = MarketService.list_market_sellers(5, {"page": 1}, user_id="U1")

    mock_search_shops.assert_called_once_with({"page": 1}, user_id="U1", market_id=5)
    assert result == {"shops": [], "pagination": {}}


@patch("app.markets.services.session_scope")
def test_list_market_sellers_raises_not_found_for_missing_market(mock_scope):
    session = MagicMock()
    session.query.return_value.get.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(NotFoundError):
        MarketService.list_market_sellers(999, {})


@patch("app.products.services.ProductService.search_products")
@patch("app.markets.services.session_scope")
def test_list_market_products_delegates_with_market_id(
    mock_scope, mock_search_products
):
    session = MagicMock()
    session.query.return_value.get.return_value = SimpleNamespace(id=5)
    mock_scope.return_value.__enter__.return_value = session
    mock_search_products.return_value = {"items": [], "pagination": {}}

    result = MarketService.list_market_products(5, {"page": 1})

    mock_search_products.assert_called_once_with({"page": 1}, market_id=5)
    assert result == {"items": [], "pagination": {}}


@patch("app.socials.services.PostService.get_posts")
@patch("app.markets.services.session_scope")
def test_list_market_posts_delegates_with_market_id(mock_scope, mock_get_posts):
    session = MagicMock()
    session.query.return_value.get.return_value = SimpleNamespace(id=5)
    mock_scope.return_value.__enter__.return_value = session
    mock_get_posts.return_value = {"items": [], "pagination": {}}

    result = MarketService.list_market_posts(5, {"page": 1})

    mock_get_posts.assert_called_once_with({"page": 1}, market_id=5)
    assert result == {"items": [], "pagination": {}}
