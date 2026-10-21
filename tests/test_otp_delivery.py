"""Rider sign-in codes go by SMS first and fall back to email."""

import logging

import pytest

from app.libs import otp_delivery
from app.libs.otp_delivery import deliver_otp
from main.config import settings

PHONE = "2348031234567"
EMAIL = "rider@markt.test"
CODE = "123456"


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.content = b"x"

    def json(self):
        return self._body


ACCEPTED = FakeResponse(
    200,
    {"code": 200, "status": "success", "message": "processing", "data": {}},
)


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(settings, "OTP_CHANNELS", "sms,email")
    monkeypatch.setattr(settings, "SENDCHAMP_API_KEY", "sk_test")
    monkeypatch.setattr(settings, "SENDCHAMP_SENDER_NAME", "Markt")
    monkeypatch.setattr(settings, "SENDCHAMP_ROUTE", "dnd")

    calls = {"sms": [], "email": []}

    def post(url, json, headers, timeout):
        calls["sms"].append({"url": url, "json": json, "headers": headers})
        return calls.get("response", ACCEPTED)

    monkeypatch.setattr(otp_delivery.requests, "post", post)
    monkeypatch.setattr(
        otp_delivery.email_service,
        "send_otp_email",
        lambda email, code: calls["email"].append(email) or True,
    )
    return calls


class TestSmsFirst:
    def test_sms_is_used_when_it_is_accepted(self, setup):
        assert deliver_otp(PHONE, EMAIL, CODE) == "sms"
        assert setup["email"] == []

    def test_the_request_matches_sendchamps_send_sms_api(self, setup):
        deliver_otp(PHONE, EMAIL, CODE)
        sent = setup["sms"][0]
        assert sent["url"] == "https://api.sendchamp.com/api/v1/sms/send"
        assert sent["headers"]["Authorization"] == "Bearer sk_test"
        assert sent["json"]["to"] == [PHONE]
        assert sent["json"]["sender_name"] == "Markt"
        assert sent["json"]["route"] == "dnd"
        assert CODE in sent["json"]["message"]

    def test_a_rider_without_email_can_still_get_a_code(self, setup):
        assert deliver_otp(PHONE, None, CODE) == "sms"


class TestEmailFallback:
    @pytest.mark.parametrize(
        "response",
        [
            FakeResponse(403, {"code": 403, "error": " insufficient funds", "status": "error"}),
            FakeResponse(400, {"code": 400, "message": "Message required", "status": "failed"}),
            FakeResponse(200, {"code": 200, "status": "failed"}),
        ],
    )
    def test_a_refused_sms_falls_back_to_email(self, setup, response):
        setup["response"] = response
        assert deliver_otp(PHONE, EMAIL, CODE) == "email"
        assert setup["email"] == [EMAIL]

    def test_a_network_error_falls_back_to_email(self, setup, monkeypatch):
        def boom(*a, **k):
            raise otp_delivery.requests.ConnectionError("down")

        monkeypatch.setattr(otp_delivery.requests, "post", boom)
        assert deliver_otp(PHONE, EMAIL, CODE) == "email"

    def test_sms_is_skipped_until_sendchamp_is_configured(self, setup, monkeypatch):
        monkeypatch.setattr(settings, "SENDCHAMP_SENDER_NAME", "")
        assert deliver_otp(PHONE, EMAIL, CODE) == "email"
        assert setup["sms"] == []

    def test_nothing_reaches_a_rider_with_no_email_when_sms_fails(self, setup):
        setup["response"] = FakeResponse(403, {"status": "error"})
        assert deliver_otp(PHONE, None, CODE) is None


class TestChannelOrder:
    def test_email_only_is_the_default(self, setup, monkeypatch):
        monkeypatch.setattr(settings, "OTP_CHANNELS", "email")
        assert deliver_otp(PHONE, EMAIL, CODE) == "email"
        assert setup["sms"] == []

    def test_unknown_names_are_ignored(self, setup, monkeypatch):
        monkeypatch.setattr(settings, "OTP_CHANNELS", "carrier_pigeon, email")
        assert deliver_otp(PHONE, EMAIL, CODE) == "email"

    def test_nothing_configured_means_nothing_sent(self, setup, monkeypatch):
        monkeypatch.setattr(settings, "OTP_CHANNELS", "")
        assert deliver_otp(PHONE, EMAIL, CODE) is None


class TestTheCodeIsNotLogged:
    def test_a_refusal_does_not_log_the_code(self, setup, caplog):
        setup["response"] = FakeResponse(400, {"status": "failed", "message": "bad"})
        with caplog.at_level(logging.DEBUG):
            deliver_otp(PHONE, EMAIL, CODE)
        assert CODE not in caplog.text

    def test_a_network_error_does_not_log_the_code(self, setup, monkeypatch, caplog):
        def boom(*a, **k):
            raise otp_delivery.requests.ConnectionError(f"failed sending {CODE}")

        monkeypatch.setattr(otp_delivery.requests, "post", boom)
        with caplog.at_level(logging.DEBUG):
            deliver_otp(PHONE, EMAIL, CODE)
        assert CODE not in caplog.text
