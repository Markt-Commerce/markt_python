"""Email verification: code generation, attempt lockout, and resend limits.

The flow existed and worked. What it had no notion of was abuse — a 6-digit
code with unlimited attempts is a 1-in-a-million guess repeated as fast as
requests can be sent, and nothing was counting.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.users import verification
from app.users.verification import (
    MAX_ATTEMPTS,
    MAX_SENDS_PER_HOUR,
    VerificationThrottled,
    generate_code,
)


class FakeRedis:
    """In-memory stand-in. No TTL simulation — expiry is Redis's job, and the
    behaviour under test is the counting."""

    def __init__(self):
        self.store = {}

    def get(self, k):
        return self.store.get(k)

    def setex(self, k, _ttl, v):
        self.store[k] = v

    def incr(self, k, amount=1):
        self.store[k] = int(self.store.get(k, 0)) + amount
        return self.store[k]

    def expire(self, k, _t):
        return True

    def delete(self, k):
        self.store.pop(k, None)


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(verification, "redis_client", fake)
    return fake


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


def test_code_is_six_digits():
    for _ in range(200):
        c = generate_code()
        assert len(c) == 6 and c.isdigit()


def test_code_keeps_leading_zeros():
    """`str(randint(100000, 999999))` could never produce 012345, which quietly
    removed 10% of the keyspace. Zero-padding restores it."""
    with patch("app.users.verification.secrets.randbelow", return_value=12345):
        assert generate_code() == "012345"


def test_code_uses_a_secure_source():
    """`random` is a Mersenne Twister — recoverable state, predictable output.
    Fine for shuffling a feed, not for a credential.

    Checks the module's imports rather than its source text: my first version
    grepped the source and passed/failed on the *docstring*, which mentions
    `random.randint` by name. That was asserting against prose.
    """
    import sys

    mod = sys.modules[verification.__name__]
    assert getattr(mod, "secrets", None) is not None, "secrets must be imported"
    assert (
        getattr(mod, "random", None) is None
    ), "the `random` module must not be reachable from the verification module"

    # And the generator must actually route through secrets.
    with patch("app.users.verification.secrets.randbelow", return_value=7) as spy:
        generate_code()
    spy.assert_called_once()


# ---------------------------------------------------------------------------
# Attempt lockout
# ---------------------------------------------------------------------------


def test_attempts_are_allowed_until_the_limit(redis):
    for i in range(MAX_ATTEMPTS):
        verification.assert_can_attempt("a@b.com")  # must not raise
        remaining = verification.record_failure("a@b.com")
        assert remaining == MAX_ATTEMPTS - (i + 1)


def test_locks_out_after_the_limit(redis):
    for _ in range(MAX_ATTEMPTS):
        verification.record_failure("a@b.com")
    with pytest.raises(VerificationThrottled) as exc:
        verification.assert_can_attempt("a@b.com")
    assert exc.value.retry_after > 0


def test_lockout_is_per_address(redis):
    for _ in range(MAX_ATTEMPTS):
        verification.record_failure("victim@b.com")
    # Someone else's failures must not lock this user out.
    verification.assert_can_attempt("other@b.com")


def test_verifying_clears_the_counters(redis):
    for _ in range(MAX_ATTEMPTS):
        verification.record_failure("a@b.com")
    verification.clear("a@b.com")
    verification.assert_can_attempt("a@b.com")


def test_email_case_does_not_bypass_the_lockout(redis):
    """Otherwise A@B.com and a@b.com are separate buckets and the limit is
    trivially defeated."""
    for _ in range(MAX_ATTEMPTS):
        verification.record_failure("a@b.com")
    with pytest.raises(VerificationThrottled):
        verification.assert_can_attempt("A@B.COM")


# ---------------------------------------------------------------------------
# Resend limits
# ---------------------------------------------------------------------------


def test_first_send_is_allowed(redis):
    verification.assert_can_send("a@b.com")


def test_cooldown_blocks_an_immediate_resend(redis):
    verification.assert_can_send("a@b.com")
    verification.record_send("a@b.com")
    with pytest.raises(VerificationThrottled):
        verification.assert_can_send("a@b.com")


def test_hourly_cap_blocks_a_mail_cannon(redis):
    """Unlimited resends are a free way to use Markt's mail quota to send
    someone email they never asked for."""
    for _ in range(MAX_SENDS_PER_HOUR):
        verification.record_send("a@b.com")
    redis.delete("emailverify:cooldown:a@b.com")  # past the per-send cooldown
    with pytest.raises(VerificationThrottled):
        verification.assert_can_send("a@b.com")


# ---------------------------------------------------------------------------
# Redis down
# ---------------------------------------------------------------------------


def test_fails_closed_when_the_limiter_is_unavailable(monkeypatch):
    """Deliberately the opposite of the cache decision elsewhere: there a
    missing cache costs a slow read, here it costs the guarantee itself."""
    broken = MagicMock()
    broken.get.side_effect = ConnectionError("redis down")
    monkeypatch.setattr(verification, "redis_client", broken)

    with pytest.raises(VerificationThrottled):
        verification.assert_can_attempt("a@b.com")
    with pytest.raises(VerificationThrottled):
        verification.assert_can_send("a@b.com")
