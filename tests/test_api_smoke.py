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
