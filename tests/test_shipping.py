"""Unit tests for shipping address normalization."""

from unittest.mock import patch

import pytest

from app.libs.errors import ValidationError
from app.orders.shipping import (
    normalize_shipping_address,
    shipping_address_to_model_kwargs,
)


def test_normalize_accepts_street_alias():
    data = normalize_shipping_address(
        {
            "recipient_name": "Test User",
            "street": "1 Market Road",
            "city": "Lagos",
            "state": "Lagos",
            "postal_code": "100001",
            "country": "Nigeria",
            "latitude": 1.0,
            "longitude": 2.0,
        }
    )
    assert data["street_address"] == "1 Market Road"


def test_normalize_rejects_empty_address():
    with pytest.raises(ValidationError) as exc:
        normalize_shipping_address({})
    assert "shipping_address is required" in exc.value.message


def test_normalize_rejects_missing_required_fields():
    with pytest.raises(ValidationError) as exc:
        normalize_shipping_address(
            {
                "street_address": "1 Road",
                "city": "Lagos",
                "state": "Lagos",
                "postal_code": "100001",
                "country": "Nigeria",
            }
        )
    assert "recipient_name" in exc.value.message


def test_normalize_accepts_address_without_postal_code():
    """A GPS-derived Nigerian address has no postcode, and must still check out.

    This was a real checkout failure: the buyer picked "current location", the
    reverse geocode returned no postal_code, and POST /cart/checkout 422'd with
    a message the app couldn't act on. Retrying could never work.
    """
    data = normalize_shipping_address(
        {
            "recipient_name": "Test User",
            "street_address": "Lagelu",
            "city": "Lagelu",
            "state": "Oyo",
            "country": "Nigeria",
            "latitude": 7.4506,
            "longitude": 3.947,
        }
    )
    assert data["postal_code"] is None
    assert data["city"] == "Lagelu"


def test_normalize_still_keeps_postal_code_when_given():
    data = normalize_shipping_address(
        {
            "recipient_name": "Test User",
            "street_address": "1 Market Road",
            "city": "Lagos",
            "state": "Lagos",
            "postal_code": "100001",
            "country": "Nigeria",
            "latitude": 1.0,
            "longitude": 2.0,
        }
    )
    assert data["postal_code"] == "100001"


@patch("app.orders.shipping.geocode_address", return_value=(6.5, 3.4))
def test_normalize_geocodes_when_coordinates_missing(mock_geocode):
    data = normalize_shipping_address(
        {
            "recipient_name": "Test User",
            "street_address": "1 Market Road",
            "city": "Lagos",
            "state": "Lagos",
            "postal_code": "100001",
            "country": "Nigeria",
        }
    )
    mock_geocode.assert_called_once()
    assert data["latitude"] == 6.5
    assert data["longitude"] == 3.4


def test_use_saved_address_merges_profile(sample_shipping_address):
    data = normalize_shipping_address(
        {"city": "Abuja"},
        saved_address=sample_shipping_address,
        use_saved_address=True,
    )
    assert data["city"] == "Abuja"
    assert data["recipient_name"] == "Ada Lovelace"


def test_shipping_address_to_model_kwargs(sample_shipping_address):
    model_kwargs = shipping_address_to_model_kwargs(sample_shipping_address)
    assert model_kwargs["street_address"] == "12 Broad Street"
    assert model_kwargs["latitude"] == 6.45
