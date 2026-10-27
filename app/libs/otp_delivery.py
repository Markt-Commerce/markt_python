"""Getting a rider's sign-in code to them.

Channels are tried in the order OTP_CHANNELS lists them, and the first that
accepts the code wins. SMS first with email behind it is the intended
production order: SMS reaches the phone the rider is holding, and email
catches what SMS drops -- an unregistered sender ID, an empty Termii
wallet, a provider outage.

"Accepted" means the provider took the message, not that it arrived.
Termii answers with a message_id and delivers later, so a code that was
accepted and then lost on the network does not fall through to email. The
rider asks for another code, which is what they would do anyway.

Generating, storing and spending the code stays in DeliveryService; this
module only carries it. That is why Termii's Token API is not used:
it generates and checks codes itself, which would bypass the single-use rule
in login_delivery_partner.
"""

import logging
from typing import List, Optional

import requests

from app.libs.email_service import email_service
from main.config import settings

logger = logging.getLogger(__name__)


class TermiiSMS:
    name = "sms"

    @staticmethod
    def url() -> str:
        # Termii gives each account its own base URL (shown on the dashboard).
        return settings.TERMII_BASE_URL.rstrip("/") + "/api/sms/send"

    @staticmethod
    def configured() -> bool:
        return bool(settings.TERMII_API_KEY and settings.TERMII_SENDER_ID)

    @staticmethod
    def send(phone: str, email: Optional[str], code: str) -> bool:
        if not TermiiSMS.configured():
            return False
        # Nothing but the code and its expiry. An OTP with a promo line on
        # it is no longer transactional traffic to the networks, and stops
        # getting through to DND numbers.
        message = (
            f"Your Markt Logistics sign-in code is {code}. It expires in "
            "10 minutes. Do not share it with anyone."
        )
        try:
            response = requests.post(
                TermiiSMS.url(),
                json={
                    # International format without the +, which is what
                    # _normalize_phone already stores.
                    "to": phone,
                    "from": settings.TERMII_SENDER_ID,
                    "sms": message,
                    "type": "plain",
                    # dnd: the transactional route. generic silently never
                    # reaches the tens of millions of numbers on the DND
                    # register.
                    "channel": settings.TERMII_CHANNEL,
                    "api_key": settings.TERMII_API_KEY,
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=10,
            )
            body = response.json() if response.content else {}
        except Exception as e:
            # The exception, never the request: the request body holds the
            # code and the API key.
            logger.error("Termii SMS send failed: %s", type(e).__name__)
            return False

        # A message_id is Termii's receipt; without one nothing was queued.
        if response.status_code == 200 and body.get("message_id"):
            return True
        # Termii puts the reason in "message" ("Insufficient balance", an
        # unapproved sender ID). It does not carry the code.
        logger.error(
            "Termii refused the SMS (%s): %s",
            response.status_code,
            body.get("message") or body.get("error") or "no reason given",
        )
        return False


class EmailOTP:
    name = "email"

    @staticmethod
    def configured() -> bool:
        return True

    @staticmethod
    def send(phone: str, email: Optional[str], code: str) -> bool:
        if not email:
            return False
        return bool(email_service.send_otp_email(email, code))


CHANNELS = {c.name: c for c in (TermiiSMS, EmailOTP)}


def channel_order() -> List:
    """The configured channels, in order, skipping unknown names."""
    names = [n.strip().lower() for n in (settings.OTP_CHANNELS or "").split(",")]
    order = []
    for name in names:
        channel = CHANNELS.get(name)
        if channel is None:
            if name:
                logger.error("Unknown OTP channel %r in OTP_CHANNELS", name)
            continue
        if channel not in order:
            order.append(channel)
    return order


def deliver_otp(phone: str, email: Optional[str], code: str) -> Optional[str]:
    """Send `code` on the first channel that takes it.

    Returns that channel's name, or None if every channel failed or none
    applied (no SMS provider configured and no email on the account).
    """
    for channel in channel_order():
        if not channel.configured():
            continue
        if channel.send(phone, email, code):
            return channel.name
        logger.warning("OTP channel %s failed; trying the next", channel.name)
    return None
