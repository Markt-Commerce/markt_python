"""Pre-authorization: hold funds now, capture the real amount later.

This is the primitive batch delivery needs. The batch fee is not knowable at
pay time -- it depends on how many other buyers join before the run's cutoff,
up to two hours away. So the buyer is quoted the *solo* fee as a ceiling, that
amount is held, and only what is actually owed is captured. A batch can make it
cheaper and never dearer.

Two things this module exists to keep honest:

  * Not every payment method can hold funds. Bank transfer and USSD take the
    money or they do not. The fallback is charge-the-ceiling-then-refund, which
    is materially worse for the buyer -- their money genuinely leaves and comes
    back over days -- so which model applies must be decided *before* they pay
    and told to them in plain words, never discovered afterwards.

  * A hold expires. Paystack's window is 5-10 days depending on the issuer,
    which is comfortably longer than a 2h run cadence, but a hold that lapses
    silently is an order that was never paid for. Expiry is tracked and acted
    on rather than assumed away.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from decouple import config

logger = logging.getLogger(__name__)


class CaptureModel(Enum):
    """How a payment's final amount gets settled."""

    # Hold the ceiling, capture the actual. Paystack releases the difference.
    PREAUTH_CAPTURE = "preauth_capture"
    # Charge the ceiling, refund the difference. Slower and visible to the
    # buyer; used when the method cannot hold.
    CHARGE_REFUND = "charge_refund"
    # Nothing to settle later -- a solo delivery at a fixed fee.
    IMMEDIATE = "immediate"


# Methods that can hold funds. Deliberately a allow-list rather than a
# deny-list: a payment method we have not considered must fall back to the
# safe, slower model rather than silently attempting a hold that will not work.
PREAUTH_CAPABLE_METHODS = frozenset({"card"})

# Paystack gates pre-authorization by currency as well as by merchant, and the
# preauthorization API accepts ZAR only -- not NGN, which is what Markt
# charges in. So on this deployment a hold is not available at any setting,
# and PAYSTACK_PREAUTH_ENABLED on its own is not enough to get one.
#
# This is a guard, not a preference. Without it, switching the flag on in an
# NGN deployment would send a hold request that Paystack answers with an
# ordinary charge -- the buyer's money actually leaving, after we told them it
# would only be held. That is the single worst outcome in this file, and it
# would look exactly like a successful preauth from our side.
#
# Verified against Paystack's Preauthorization API documentation (September
# 2026), which states only ZAR is supported. Revisit if that changes, or if
# delivery ever settles through a processor that holds NGN.
PREAUTH_SUPPORTED_CURRENCIES = frozenset({"ZAR"})


def deployment_currency() -> str:
    """What this deployment charges in. Matches main.config's PAYMENT_CURRENCY
    so the two cannot drift into disagreeing about the same account."""
    return config("PAYMENT_CURRENCY", default="NGN")


def preauth_enabled() -> bool:
    """Whether pre-authorization is switched on for this deployment.

    Paystack gates pre-authorization per merchant, so this cannot be inferred
    from the API -- it is a fact about the account that someone has to tell us.
    Defaults to off: attempting a hold on an account without it produces a
    charge, and a buyer charged the ceiling when they were promised a hold is
    the worst outcome in this file.
    """
    return config("PAYSTACK_PREAUTH_ENABLED", default=False, cast=bool)


def capture_model_for(
    method: Optional[str], *, settles_later: bool, currency: Optional[str] = None
) -> CaptureModel:
    """Which model applies to this payment.

    `settles_later` is true when the final amount is not yet known -- the buyer
    opted into a batch. A solo delivery has a fixed fee and nothing to settle,
    so it charges immediately whatever the method.

    A hold needs three things to be true at once: the merchant account has
    pre-authorization switched on, the currency is one Paystack will hold, and
    the method can hold at all. Any one of them missing falls back to
    charge-then-refund, which is slower and visible to the buyer but always
    works. Falling back is never silent -- describe_for_buyer says which one
    applies before they pay.
    """
    if not settles_later:
        return CaptureModel.IMMEDIATE

    normalised = (method or "").strip().lower()
    holdable_currency = (
        currency or deployment_currency()
    ).strip().upper() in PREAUTH_SUPPORTED_CURRENCIES

    if (
        preauth_enabled()
        and holdable_currency
        and normalised in PREAUTH_CAPABLE_METHODS
    ):
        return CaptureModel.PREAUTH_CAPTURE
    return CaptureModel.CHARGE_REFUND


# How long a hold is assumed good for. The short end of Paystack's stated
# 5-10 day range, because assuming the generous end is how a hold lapses.
HOLD_VALID_DAYS = 5


def hold_expires_at(authorized_at: Optional[datetime] = None) -> datetime:
    return (authorized_at or datetime.utcnow()) + timedelta(days=HOLD_VALID_DAYS)


def describe_for_buyer(model: CaptureModel, ceiling_minor: int) -> str:
    """The sentence shown before paying.

    Not decoration. Under CHARGE_REFUND the buyer's money leaves and comes
    back, and finding that out afterwards feels like a mistake on our part
    even when it is exactly what was supposed to happen.
    """
    amount = f"₦{ceiling_minor / 100:,.2f}"
    if model is CaptureModel.PREAUTH_CAPTURE:
        return (
            f"We'll hold {amount}. If your delivery is shared, "
            f"you'll only be charged the lower amount."
        )
    if model is CaptureModel.CHARGE_REFUND:
        return (
            f"We'll charge {amount} now. If your delivery is shared, "
            f"we'll refund the difference within a few days."
        )
    return f"You'll be charged {amount}."
