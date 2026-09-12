"""HTTP smoke tests for Phase 0 routes (Flask test client)."""

from unittest.mock import MagicMock, patch

import pytest

from main.setup import create_app


@pytest.fixture
def app():
    flask_app, _socketio = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


class TestDeprecatedOrderCreateEndpoint:
    @patch("flask_login.utils._get_user")
    def test_post_orders_returns_410(self, mock_get_user, client):
        user = MagicMock()
        user.is_authenticated = True
        user.is_buyer = True
        user.buyer_account = MagicMock(id=1)
        mock_get_user.return_value = user

        response = client.post(
            "/api/v1/orders/",
            json={
                "cart_id": 1,
                "shipping_address": {"street": "x"},
                "payment_method": "card",
            },
        )

        assert response.status_code == 410
        body = response.get_json()
        assert "deprecated" in body["message"].lower()
        assert body["replacement"] == "/api/v1/cart/checkout"
        assert response.headers.get("Deprecation") == "true"


class TestCheckoutAuthSmoke:
    def test_checkout_requires_auth(self, client):
        response = client.post(
            "/api/v1/cart/checkout",
            json={
                "shipping_address": {},
                "billing_address": {},
            },
        )
        assert response.status_code == 401


class TestWalletAuthSmoke:
    def test_wallet_requires_auth(self, client):
        response = client.get("/api/v1/wallet/")
        assert response.status_code == 401


class TestOrderCancelAuthSmoke:
    def test_cancel_requires_auth(self, client):
        response = client.post("/api/v1/orders/ORD_TEST01/cancel", json={})
        assert response.status_code == 401


class TestOrderTrackAuthSmoke:
    def test_track_requires_auth(self, client):
        response = client.get("/api/v1/orders/ORD_TEST01/track")
        assert response.status_code == 401


class TestWalletWithdrawalsAuthSmoke:
    def test_withdrawals_requires_auth(self, client):
        response = client.get("/api/v1/wallet/withdrawals")
        assert response.status_code == 401


class TestMarketBrowsingSmoke:
    """13/mobile: market list -> market detail -> sellers/products/posts in
    it. Confirms the blueprint is actually registered and wired end-to-end
    through flask-smorest, without touching a real database."""

    @patch("app.markets.services.MarketService.list_markets")
    def test_list_markets(self, mock_list, client):
        mock_list.return_value = [
            {
                "id": 1,
                "name": "Bodija",
                "slug": "bodija",
                "latitude": None,
                "longitude": None,
                "is_active": True,
                "seller_count": 3,
            }
        ]
        response = client.get("/api/v1/markets/")
        assert response.status_code == 200
        assert response.get_json()["markets"][0]["name"] == "Bodija"

    @patch("app.markets.services.MarketService.get_market")
    def test_get_market_not_found(self, mock_get, client):
        from app.libs.errors import NotFoundError

        mock_get.side_effect = NotFoundError("Market not found")
        response = client.get("/api/v1/markets/999")
        assert response.status_code == 404

    @patch("app.markets.services.MarketService.list_market_sellers")
    def test_market_sellers(self, mock_list, client):
        mock_list.return_value = {"shops": [], "pagination": {}}
        response = client.get("/api/v1/markets/1/sellers")
        assert response.status_code == 200
        mock_list.assert_called_once()

    @patch("app.markets.services.MarketService.list_market_products")
    def test_market_products(self, mock_list, client):
        mock_list.return_value = {
            "items": [],
            "pagination": {
                "page": 1,
                "per_page": 20,
                "total_items": 0,
                "total_pages": 0,
            },
        }
        response = client.get("/api/v1/markets/1/products")
        assert response.status_code == 200

    @patch("app.markets.services.MarketService.list_market_posts")
    def test_market_posts(self, mock_list, client):
        mock_list.return_value = {
            "items": [],
            "pagination": {
                "page": 1,
                "per_page": 20,
                "total_items": 0,
                "total_pages": 0,
            },
        }
        response = client.get("/api/v1/markets/1/posts")
        assert response.status_code == 200
