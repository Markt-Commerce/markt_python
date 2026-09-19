"""Paystack Transfer API helpers for wallet withdrawals."""

import logging
from typing import Any, Dict

import requests

from app.libs.errors import APIError

logger = logging.getLogger(__name__)


class PaystackTransferClient:
    BASE_URL = "https://api.paystack.co"

    @classmethod
    def _headers(cls) -> Dict[str, str]:
        from app.payments.services import PaymentService

        if not PaymentService.PAYSTACK_SECRET_KEY:
            raise APIError("Paystack is not configured", 503)
        return {"Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"}

    @classmethod
    def create_transfer_recipient(
        cls,
        *,
        account_name: str,
        account_number: str,
        bank_code: str,
        currency: str = "NGN",
    ) -> str:
        payload = {
            "type": "nuban",
            "name": account_name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": currency,
        }
        response = requests.post(
            f"{cls.BASE_URL}/transferrecipient",
            json=payload,
            headers=cls._headers(),
            timeout=30,
        )
        data = response.json()
        if response.status_code != 200 or not data.get("status"):
            logger.error("Paystack recipient creation failed: %s", data)
            raise APIError("Failed to verify bank account with Paystack", 502)

        return data["data"]["recipient_code"]

    @classmethod
    def initiate_transfer(
        cls,
        *,
        amount_kobo: int,
        recipient_code: str,
        reference: str,
        reason: str = "Markt wallet withdrawal",
    ) -> Dict[str, Any]:
        payload = {
            "source": "balance",
            "amount": amount_kobo,
            "recipient": recipient_code,
            "reason": reason,
            "reference": reference,
        }
        response = requests.post(
            f"{cls.BASE_URL}/transfer",
            json=payload,
            headers=cls._headers(),
            timeout=30,
        )
        data = response.json()
        if response.status_code != 200 or not data.get("status"):
            logger.error("Paystack transfer failed: %s", data)
            message = data.get("message", "Transfer initiation failed")
            raise APIError(message, 502)

        return data
