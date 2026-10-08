"""Paystack bank list and account-name resolution.

Withdrawals used to take a hand-typed bank code and account name. A typo went
straight to Paystack's transfer-recipient call and came back as a failed
withdrawal, after the wallet had already been debited. These two endpoints let
the client show a picker and confirm the real account name before anything is
submitted.
"""

import json
import logging
from typing import Any, Dict, List

import requests

from app.libs.errors import APIError, ValidationError
from external.redis import redis_client

logger = logging.getLogger(__name__)

BANK_LIST_CACHE_KEY = "paystack:banks:{currency}"
# The Nigerian bank list is ~280 entries and changes a few times a year, so a
# day of staleness is harmless and saves a round trip on every withdrawal.
BANK_LIST_TTL_SECONDS = 24 * 60 * 60


class PaystackBankClient:
    BASE_URL = "https://api.paystack.co"

    @classmethod
    def _headers(cls) -> Dict[str, str]:
        from app.payments.services import PaymentService

        if not PaymentService.PAYSTACK_SECRET_KEY:
            raise APIError("Paystack is not configured", 503)
        return {"Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"}

    @classmethod
    def list_banks(cls, currency: str = "NGN") -> List[Dict[str, Any]]:
        cache_key = BANK_LIST_CACHE_KEY.format(currency=currency)

        try:
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as exc:  # cache is an optimisation, never a dependency
            logger.warning("Bank list cache read failed: %s", exc)

        response = requests.get(
            f"{cls.BASE_URL}/bank",
            params={"currency": currency},
            headers=cls._headers(),
            timeout=20,
        )
        body = response.json()
        if response.status_code != 200 or not body.get("status"):
            logger.error("Paystack bank list failed: %s", body)
            raise APIError("Could not load the bank list", 502)

        # Only what a picker needs. Paystack returns a dozen fields per bank;
        # forwarding all of them would tie the client to their payload shape.
        #
        # `id` is included because `code` is not unique and the client
        # needs something that is -- see the dedupe below.
        rows = [
            {
                "id": b.get("id"),
                "name": b.get("name"),
                "code": b.get("code"),
                "slug": b.get("slug"),
                "type": b.get("type"),
            }
            for b in (body.get("data") or [])
            if b.get("active") and b.get("code")
        ]

        banks = PaystackBankClient._dedupe_by_code(rows)
        banks.sort(key=lambda b: (b["name"] or "").lower())

        try:
            redis_client.setex(cache_key, BANK_LIST_TTL_SECONDS, json.dumps(banks))
        except Exception as exc:
            logger.warning("Bank list cache write failed: %s", exc)

        return banks

    @staticmethod
    def _dedupe_by_code(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """One row per bank code.

        Paystack's list is not unique on `code` -- five NGN codes come
        back twice under two registered names, e.g. 50572 as both
        "BANKIT MFB" and "BANKIT MICROFINANCE BANK LTD". The duplicates
        crashed the rider app's list, which keyed rows by code, and they
        were noise regardless: `code` is the entire destination of a
        transfer, so two rows carrying the same one do exactly the same
        thing whichever is picked.

        The shorter name wins, because these pairs are consistently a
        readable name and its registry spelling -- "U and C MFB" against
        "U&C Microfinance Bank Ltd (U AND C MFB)" -- and the readable one
        is what somebody is scanning a list for.
        """
        by_code: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            code = row["code"]
            kept = by_code.get(code)
            if kept is None or len(row["name"] or "") < len(kept["name"] or ""):
                by_code[code] = row
        return list(by_code.values())

    @classmethod
    def resolve_account(cls, account_number: str, bank_code: str) -> Dict[str, Any]:
        """Ask Paystack who owns an account, so the user can confirm before
        withdrawing to it."""
        if not account_number or not bank_code:
            raise ValidationError("Account number and bank code are required")

        response = requests.get(
            f"{cls.BASE_URL}/bank/resolve",
            params={"account_number": account_number, "bank_code": bank_code},
            headers=cls._headers(),
            timeout=20,
        )
        body = response.json()

        if response.status_code == 200 and body.get("status"):
            data = body.get("data") or {}
            return {
                "account_number": data.get("account_number", account_number),
                "account_name": data.get("account_name"),
                "bank_code": bank_code,
                "resolved": True,
            }

        # Paystack answers a bad account/bank pairing with 422 and a usable
        # message. Surface that rather than a generic failure -- the user needs
        # to know it was the digits, not the service.
        if response.status_code in (400, 422):
            raise ValidationError(
                body.get("message") or "Could not verify that account number"
            )

        logger.error("Paystack account resolve failed: %s", body)
        raise APIError("Could not verify the account right now", 502)
