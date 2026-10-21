"""The rider sign-in code.

It was a password with an hour's life on it: never consumed on use, so it
kept working until it expired, and written into the logs in plaintext on its
way out.
"""

import pytest

from app.deliveries.services import DeliveryService
from app.libs.errors import ValidationError


class FakeRedis:
    def __init__(self, initial=None):
        self.store = dict(initial or {})
        self.deleted = []

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def delete(self, key):
        self.deleted.append(key)
        self.store.pop(key, None)


PHONE = "2348031234567"
KEY = f"otp_cache:{PHONE}"


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis({KEY: "123456"})
    monkeypatch.setattr("app.deliveries.services.redis_client", fake)
    return fake


class TestTheCodeIsSpentWhenUsed:
    def test_a_wrong_code_does_not_spend_the_real_one(self, redis):
        with pytest.raises(ValidationError):
            DeliveryService.login_delivery_partner(PHONE, "000000")
        assert redis.store.get(KEY) == "123456"

    def test_the_code_is_deleted_before_the_partner_is_looked_up(
        self, redis, monkeypatch
    ):
        # Deleting only after a successful lookup would let someone probe
        # phone numbers while keeping a working code in hand.
        monkeypatch.setattr(
            "app.deliveries.services.session_scope",
            lambda: (_ for _ in ()).throw(RuntimeError("no db")),
        )
        with pytest.raises(Exception):
            DeliveryService.login_delivery_partner(PHONE, "123456")
        assert KEY in redis.deleted
        assert redis.store.get(KEY) is None

    def test_a_spent_code_is_refused(self, redis, monkeypatch):
        monkeypatch.setattr(
            "app.deliveries.services.session_scope",
            lambda: (_ for _ in ()).throw(RuntimeError("no db")),
        )
        with pytest.raises(Exception):
            DeliveryService.login_delivery_partner(PHONE, "123456")

        # Second attempt with the same code: refused at the OTP check, which
        # is a ValidationError, not the database error above.
        with pytest.raises(ValidationError):
            DeliveryService.login_delivery_partner(PHONE, "123456")


class TestTheCodeDoesNotOutliveItsUsefulness:
    def test_it_expires_in_minutes_not_hours(self):
        assert DeliveryService.CACHE_EXPIRE_SECONDS <= 900


class TestTheCodeIsNotLogged:
    def test_send_otp_does_not_put_the_code_in_a_log_line(self):
        import inspect

        source = inspect.getsource(DeliveryService.send_otp)
        # The f-string that interpolated `otp` into a log message.
        assert "OTP {otp}" not in source
        assert "{otp}" not in source


class TestTheResponseDoesNotHandOutTheAddress:
    """The OTP endpoint needs no authentication, and a rider's phone number
    is printed on every package they deliver."""

    def test_the_address_is_masked_not_returned(self):
        from app.deliveries.services import _mask_email

        masked = _mask_email("adebowale@gmail.com")
        assert "adebowale" not in masked
        assert masked.startswith("a")
        assert masked.endswith("@gmail.com")

    def test_enough_survives_to_recognise_your_own_inbox(self):
        from app.deliveries.services import _mask_email

        assert _mask_email("rider@markt.test").startswith("r")
        assert "@markt.test" in _mask_email("rider@markt.test")

    def test_a_one_letter_name_is_still_masked(self):
        from app.deliveries.services import _mask_email

        # Not "a@x.com", which would be the whole address.
        assert _mask_email("a@x.com") == "a*@x.com"

    def test_junk_does_not_raise_or_leak(self):
        from app.deliveries.services import _mask_email

        assert _mask_email("") == "your email"
        assert _mask_email("not-an-email") == "your email"

    def test_a_failed_send_does_not_name_the_address_either(self):
        import inspect

        from app.deliveries.services import DeliveryService

        source = inspect.getsource(DeliveryService.send_otp)
        assert "Failed to send OTP to {email}" not in source


DEMO_PHONE = "2348000000001"
DEMO_KEY = f"otp_cache:{DEMO_PHONE}"


@pytest.fixture
def demo(monkeypatch):
    """A demo rider configured, Redis faked, and email made to fail loudly."""
    from main.config import settings

    fake = FakeRedis()
    monkeypatch.setattr("app.deliveries.services.redis_client", fake)
    monkeypatch.setattr(settings, "DELIVERY_DEMO_PHONE", "+" + DEMO_PHONE)
    monkeypatch.setattr(settings, "DELIVERY_DEMO_OTP", "424242")

    sent = []
    monkeypatch.setattr(
        "app.libs.otp_delivery.email_service.send_otp_email",
        lambda email, code: sent.append(email) or True,
    )
    return fake, sent, settings


class TestTheStoreReviewDemoRider:
    """Apple and Google reviewers sign in with a fixed code they were given
    in the review notes, because they cannot receive one."""

    def test_the_demo_number_gets_the_fixed_code_and_no_email(self, demo):
        fake, sent, _ = demo
        result = DeliveryService.send_otp(DEMO_PHONE)
        assert result["status"] == "success"
        assert fake.store[DEMO_KEY] == "424242"
        assert sent == []

    def test_the_fixed_code_is_spent_on_use_like_any_other(self, demo, monkeypatch):
        fake, _, _ = demo
        DeliveryService.send_otp(DEMO_PHONE)
        monkeypatch.setattr(
            "app.deliveries.services.session_scope",
            lambda: (_ for _ in ()).throw(RuntimeError("no db")),
        )
        with pytest.raises(Exception):
            DeliveryService.login_delivery_partner(DEMO_PHONE, "424242")
        with pytest.raises(ValidationError):
            DeliveryService.login_delivery_partner(DEMO_PHONE, "424242")

    def test_other_numbers_are_untouched(self, demo):
        from app.deliveries.services import _demo_otp_for

        assert _demo_otp_for(PHONE) is None

    def test_no_demo_account_unless_both_settings_are_set(self, demo, monkeypatch):
        from app.deliveries.services import _demo_otp_for

        _, _, settings = demo
        monkeypatch.setattr(settings, "DELIVERY_DEMO_OTP", "")
        assert _demo_otp_for(DEMO_PHONE) is None

    @pytest.mark.parametrize("bad", ["1234", "abcdef", "1234567"])
    def test_a_code_that_is_not_six_digits_turns_it_off(self, demo, monkeypatch, bad):
        from app.deliveries.services import _demo_otp_for

        _, _, settings = demo
        monkeypatch.setattr(settings, "DELIVERY_DEMO_OTP", bad)
        assert _demo_otp_for(DEMO_PHONE) is None
