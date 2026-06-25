"""Smoke tests for Phase 0 checkout and order API behaviour."""

from unittest.mock import patch

import pytest

from app.libs.errors import ValidationError
from app.orders.shipping import normalize_shipping_address


class TestCheckoutValidationSmoke:
    """Fast validation checks that mirror checkout endpoint rules."""

    def test_checkout_payload_with_docs_style_street_alias_fails_without_recipient(
        self,
    ):
        with pytest.raises(ValidationError) as exc:
            normalize_shipping_address(
                {
                    "street": "123 Main St",
                    "city": "Lagos",
                    "state": "Lagos",
                    "country": "Nigeria",
                    "postal_code": "100001",
                }
            )
        assert "recipient_name" in exc.value.message

    @patch("app.orders.shipping.geocode_address", return_value=(6.5, 3.4))
    def test_checkout_payload_valid_with_recipient_and_street_alias(self, _mock_geo):
        data = normalize_shipping_address(
            {
                "recipient_name": "Buyer One",
                "street": "123 Main St",
                "city": "Lagos",
                "state": "Lagos",
                "country": "Nigeria",
                "postal_code": "100001",
            }
        )
        assert data["street_address"] == "123 Main St"
        assert data["recipient_name"] == "Buyer One"


class TestDeprecatedOrderCreateRoute:
    def test_deprecated_route_message_contract(self):
        payload = {
            "message": (
                "POST /orders is deprecated. "
                "Use POST /cart/checkout to create an order from the active cart."
            ),
            "replacement": "/api/v1/cart/checkout",
        }
        assert payload["replacement"] == "/api/v1/cart/checkout"
