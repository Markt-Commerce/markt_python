"""Paystack subaccount helpers for seller split payments."""

import logging
from typing import Any, Dict

import requests

from app.libs.errors import APIError

logger = logging.getLogger(__name__)


class PaystackSubaccountClient:
    BASE_URL = "https://api.paystack.co"

    @classmethod
    def _headers(cls) -> Dict[str, str]:
        from app.payments.services import PaymentService

        if not PaymentService.PAYSTACK_SECRET_KEY:
            raise APIError("Paystack is not configured", 503)
        return {"Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"}

    @classmethod
    def create_subaccount(
        cls,
        *,
        business_name: str,
        bank_code: str,
        account_number: str,
        percentage_charge: float,
    ) -> Dict[str, Any]:
        """Create a Paystack subaccount for a seller."""
        payload = {
            "business_name": business_name,
            "settlement_bank": bank_code,
            "account_number": account_number,
            "percentage_charge": percentage_charge,
            "description": f"Markt seller subaccount for {business_name}",
        }
        response = requests.post(
            f"{cls.BASE_URL}/subaccount",
            json=payload,
            headers=cls._headers(),
            timeout=30,
        )
        data = response.json()
        if response.status_code != 200 or not data.get("status"):
            logger.error("Paystack subaccount creation failed: %s", data)
            raise APIError("Failed to create seller payout account", 502)
        return data["data"]
