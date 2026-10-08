"""Delivery-partner login now issues the same stateless bearer token
users/routes.py already issues for buyers/sellers (app/libs/auth_tokens.py) --
the rider app (markt_logistics) can't rely on Flask session cookies
persisting across Expo Go restarts, same reasoning as the buyer/seller app.

No existing test in this repo spins up a real Flask app (everything else is
service-level with mocks), so this builds the smallest possible app context
needed for generate_auth_token's current_app.config["SECRET_KEY"] lookup,
rather than the full create_flask_app factory (which would pull in DB/Redis
config this test doesn't need).
"""

from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from app.deliveries.models import DeliveryStatus
from app.deliveries.routes import DeliveryLogin
from app.libs.auth_tokens import verify_auth_token


def _app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    return app


def _fake_delivery_user():
    return SimpleNamespace(
        id="DEL_abc123",
        name="Test Rider",
        status=DeliveryStatus.ACTIVE,
    )


@patch("app.deliveries.routes.login_user")
@patch("app.deliveries.routes.DeliveryService.login_delivery_partner")
def test_login_response_includes_valid_access_token(mock_login, mock_login_user):
    delivery_user = _fake_delivery_user()
    mock_login.return_value = delivery_user

    app = _app()
    payload = {"phone_number": "2348012345678", "otp": "123456"}
    with app.test_request_context(json=payload):
        response = DeliveryLogin().post()
        result = response.get_json()
        assert result["partner"]["id"] == "DEL_abc123"
        assert verify_auth_token(result["access_token"]) == "DEL_abc123"

    mock_login_user.assert_called_once_with(delivery_user)
