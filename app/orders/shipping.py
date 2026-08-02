"""Shared shipping-address validation and normalization for checkout and orders."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import requests

from app.libs.errors import ValidationError

logger = logging.getLogger(__name__)

REQUIRED_SHIPPING_FIELDS = (
    "recipient_name",
    "street_address",
    "city",
    "state",
    "postal_code",
    "country",
)


def normalize_shipping_address(
    data: Optional[Dict[str, Any]],
    *,
    saved_address: Optional[Dict[str, Any]] = None,
    use_saved_address: bool = False,
) -> Dict[str, Any]:
    """Validate and normalize a shipping address payload.

    Accepts ``street`` as an alias for ``street_address``.
    When ``use_saved_address`` is true, missing fields are filled from ``saved_address``.
    """
    if use_saved_address and saved_address:
        base = dict(saved_address)
        if data:
            base.update({k: v for k, v in data.items() if v is not None})
        data = base

    if not data:
        raise ValidationError("shipping_address is required")

    normalized = {
        "recipient_name": data.get("recipient_name"),
        "street_address": data.get("street_address") or data.get("street"),
        "city": data.get("city"),
        "state": data.get("state"),
        "postal_code": data.get("postal_code") or data.get("zip"),
        "country": data.get("country"),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
    }

    missing = [field for field in REQUIRED_SHIPPING_FIELDS if not normalized.get(field)]
    if missing:
        raise ValidationError(
            f"Missing required shipping address field(s): {', '.join(missing)}"
        )

    if normalized["latitude"] is None or normalized["longitude"] is None:
        lat, lon = geocode_address(normalized)
        normalized["latitude"] = lat
        normalized["longitude"] = lon

    return normalized


def geocode_address(address_dict: Dict[str, Any]) -> Tuple[float, float]:
    """Resolve coordinates from address using Nominatim. Returns (0.0, 0.0) on failure."""
    try:
        address_parts = [
            address_dict.get("street_address", ""),
            address_dict.get("city", ""),
            address_dict.get("state", ""),
            address_dict.get("postal_code", ""),
            address_dict.get("country", ""),
        ]
        address_str = ", ".join(part for part in address_parts if part)
        if not address_str:
            return 0.0, 0.0

        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address_str, "format": "json", "limit": 1},
            headers={"User-Agent": "Markt-Commerce/1.0"},
            timeout=10,
        )
        response.raise_for_status()
        results = response.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as exc:
        logger.warning("Failed to geocode address: %s", exc)
    return 0.0, 0.0


def shipping_address_to_model_kwargs(normalized: Dict[str, Any]) -> Dict[str, Any]:
    """Map normalized dict to ``ShippingAddress`` column kwargs."""
    return {
        "recipient_name": normalized["recipient_name"],
        "street_address": normalized["street_address"],
        "city": normalized["city"],
        "state": normalized["state"],
        "postal_code": normalized["postal_code"],
        "country": normalized["country"],
        "latitude": normalized["latitude"],
        "longitude": normalized["longitude"],
    }
