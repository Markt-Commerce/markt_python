"""Rate limiting and attempt lockout for email verification.

The verification flow already existed and worked; what it had no notion of was
abuse. A 6-digit code with unlimited attempts is a **1-in-a-million guess
repeated as fast as you can send requests** — a few thousand requests is a
meaningful chance of hitting it, and nothing was counting. Unlimited resends
are equally a free way to use Markt's Resend quota to mail somebody.

All state lives in Redis with a TTL, so nothing needs cleaning up and a restart
cannot leave an account locked forever.

Redis being unavailable is treated as **fail-closed** for verification but not
for the rest of the app: if the limiter cannot be consulted, we refuse the
attempt rather than silently granting unlimited ones. That is the opposite of
the cache decision elsewhere in this codebase, and deliberately so — there, a
missing cache costs a slow read; here it costs the guarantee itself.
"""

from __future__ import annotations

import logging
import secrets

from external.redis import redis_client

logger = logging.getLogger(__name__)

# A wrong code is cheap for a human and expensive for a script.
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60

# Long enough to receive an email; short enough that a leaked code is stale.
CODE_TTL_SECONDS = 10 * 60

# Enough to cover "it didn't arrive" without becoming a mail cannon.
RESEND_COOLDOWN_SECONDS = 60
MAX_SENDS_PER_HOUR = 5

_ATTEMPTS = "emailverify:attempts:{email}"
_COOLDOWN = "emailverify:cooldown:{email}"
_SENDS = "emailverify:sends:{email}"


class VerificationThrottled(Exception):
    """Too many attempts or sends. Carries seconds until the caller may retry."""

    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


def generate_code() -> str:
    """A 6-digit code from a cryptographically secure source.

    This used `random.randint`, which is a Mersenne Twister: given enough
    outputs its state is recoverable and every later code is predictable. That
    is fine for shuffling a feed and not for a credential.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def assert_can_send(email: str) -> None:
    """Raise if this address has asked for a code too recently or too often."""
    key = email.lower()
    try:
        if redis_client.get(_COOLDOWN.format(email=key)):
            raise VerificationThrottled(
                "Please wait a moment before asking for another code.",
                retry_after=RESEND_COOLDOWN_SECONDS,
            )
        if _int(redis_client.get(_SENDS.format(email=key))) >= MAX_SENDS_PER_HOUR:
            raise VerificationThrottled(
                "Too many codes requested. Please try again in an hour.",
                retry_after=3600,
            )
    except VerificationThrottled:
        raise
    except Exception:
        logger.warning(
            "verification: limiter unavailable, refusing send", exc_info=True
        )
        raise VerificationThrottled(
            "We can't send a code right now. Please try again shortly."
        )


def record_send(email: str) -> None:
    key = email.lower()
    try:
        redis_client.setex(_COOLDOWN.format(email=key), RESEND_COOLDOWN_SECONDS, "1")
        sends_key = _SENDS.format(email=key)
        redis_client.incr(sends_key)
        # Only set the window on the first send, so the hour is a fixed window
        # and not one a caller can extend by sending again.
        if _int(redis_client.get(sends_key)) == 1:
            redis_client.expire(sends_key, 3600)
    except Exception:
        logger.warning("verification: could not record send", exc_info=True)


def assert_can_attempt(email: str) -> None:
    """Raise if this address is locked out from guessing."""
    key = email.lower()
    try:
        if _int(redis_client.get(_ATTEMPTS.format(email=key))) >= MAX_ATTEMPTS:
            raise VerificationThrottled(
                "Too many incorrect codes. Please request a new one in 15 minutes.",
                retry_after=LOCKOUT_SECONDS,
            )
    except VerificationThrottled:
        raise
    except Exception:
        logger.warning(
            "verification: limiter unavailable, refusing attempt", exc_info=True
        )
        raise VerificationThrottled(
            "We can't check that code right now. Please try again shortly."
        )


def record_failure(email: str) -> int:
    """Count a wrong code. Returns attempts remaining."""
    key = email.lower()
    try:
        attempts_key = _ATTEMPTS.format(email=key)
        used = redis_client.incr(attempts_key)
        if _int(used) == 1:
            redis_client.expire(attempts_key, LOCKOUT_SECONDS)
        return max(0, MAX_ATTEMPTS - _int(used))
    except Exception:
        logger.warning("verification: could not record failure", exc_info=True)
        return 0


def clear(email: str) -> None:
    """Wipe the counters once verified, so a later change of email starts clean."""
    key = email.lower()
    for template in (_ATTEMPTS, _COOLDOWN, _SENDS):
        try:
            redis_client.delete(template.format(email=key))
        except Exception:
            pass
