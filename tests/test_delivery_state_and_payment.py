"""The delivery state machine, the capture model, and the logistics boundary.

Pure logic, so no database: what is worth pinning is which transitions are
legal, which capture model a payment method gets, and that an unrecognised
courier webhook is ignored rather than crashing.
"""

import pytest

from app.delivery_pricing.logistics import (
    InternalFleetAdapter,
    JobRequest,
    PartnerStubAdapter,
    apply_status,
    get_adapter,
    register_adapter,
)
from app.delivery_pricing.order_delivery import DeliveryState, OrderDelivery
from app.payments.preauth import (
    CaptureModel,
    capture_model_for,
    describe_for_buyer,
    hold_expires_at,
)


def _delivery(state=DeliveryState.QUOTED, **kw):
    d = OrderDelivery()
    d.order_id = kw.get("order_id", "ORD_TEST")
    d.state = state
    d.fee_minor = kw.get("fee_minor", 50_000)
    d.solo_fee_minor = kw.get("solo_fee_minor", 50_000)
    d.settled_fee_minor = kw.get("settled_fee_minor")
    d.breakdown = {}
    return d


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def test_the_happy_path_walks_end_to_end():
    d = _delivery()
    for state in (
        DeliveryState.PAID,
        DeliveryState.JOB_CREATED,
        DeliveryState.ASSIGNED,
        DeliveryState.PICKED_UP,
        DeliveryState.IN_TRANSIT,
        DeliveryState.DELIVERED,
    ):
        d.transition_to(state)
    assert d.state is DeliveryState.DELIVERED


def test_a_delivered_parcel_is_terminal():
    d = _delivery(DeliveryState.DELIVERED)
    with pytest.raises(ValueError):
        d.transition_to(DeliveryState.IN_TRANSIT)


def test_paid_but_undispatched_has_somewhere_to_go():
    """The dangerous state: the money is good and the buyer is owed a
    delivery, but no job exists. It must park somewhere an operator can see
    rather than pretending dispatch succeeded."""
    d = _delivery(DeliveryState.PAID)
    d.transition_to(DeliveryState.AWAITING_DISPATCH)
    d.transition_to(DeliveryState.JOB_CREATED)
    assert d.state is DeliveryState.JOB_CREATED


def test_a_parcel_cannot_be_cancelled_once_it_is_in_someones_hands():
    """Past pickup, cancelling stops being a state change and becomes a
    return -- a different process with its own cost."""
    for state in (DeliveryState.PICKED_UP, DeliveryState.IN_TRANSIT):
        with pytest.raises(ValueError):
            _delivery(state).transition_to(DeliveryState.CANCELLED)


def test_cancelling_is_allowed_right_up_to_pickup():
    for state in (
        DeliveryState.QUOTED,
        DeliveryState.PAID,
        DeliveryState.AWAITING_DISPATCH,
        DeliveryState.JOB_CREATED,
        DeliveryState.ASSIGNED,
    ):
        d = _delivery(state)
        d.transition_to(DeliveryState.CANCELLED)
        assert d.state is DeliveryState.CANCELLED


def test_a_failed_delivery_can_be_retried():
    """The parcel still exists. A failure is not the end of it."""
    d = _delivery(DeliveryState.FAILED)
    d.transition_to(DeliveryState.ASSIGNED)
    assert d.state is DeliveryState.ASSIGNED


def test_a_transition_records_when_it_happened():
    d = _delivery()
    assert d.last_status_at is None
    d.transition_to(DeliveryState.PAID)
    assert d.last_status_at is not None


# ---------------------------------------------------------------------------
# What the buyer owes
# ---------------------------------------------------------------------------


def test_before_a_batch_closes_the_buyer_owes_the_solo_fee():
    """The number they agreed to, and the ceiling they can be charged."""
    d = _delivery(solo_fee_minor=50_000)
    assert d.effective_fee_minor == 50_000
    assert d.is_settled is False


def test_after_a_batch_closes_the_buyer_owes_the_settled_fee():
    d = _delivery(solo_fee_minor=50_000, settled_fee_minor=20_000)
    assert d.effective_fee_minor == 20_000
    assert d.is_settled is True


def test_a_settled_fee_of_zero_is_still_settled():
    """`if settled_fee_minor:` would treat a free delivery as unsettled and
    charge the ceiling."""
    d = _delivery(solo_fee_minor=50_000, settled_fee_minor=0)
    assert d.is_settled is True
    assert d.effective_fee_minor == 0


# ---------------------------------------------------------------------------
# Capture model
# ---------------------------------------------------------------------------


def test_a_solo_delivery_charges_immediately_whatever_the_method():
    for method in ("card", "bank_transfer", "wallet", None):
        assert capture_model_for(method, settles_later=False) is CaptureModel.IMMEDIATE


def test_without_confirmed_preauth_everything_falls_back(monkeypatch):
    """Defaults to off. Attempting a hold on an account that does not have it
    produces a charge, and a buyer charged the ceiling when they were promised
    a hold is the worst outcome here."""
    monkeypatch.setattr("app.payments.preauth.preauth_enabled", lambda: False)
    assert capture_model_for("card", settles_later=True) is CaptureModel.CHARGE_REFUND


def test_with_preauth_enabled_cards_hold(monkeypatch):
    monkeypatch.setattr("app.payments.preauth.preauth_enabled", lambda: True)
    assert capture_model_for("card", settles_later=True) is CaptureModel.PREAUTH_CAPTURE
    assert capture_model_for("CARD", settles_later=True) is CaptureModel.PREAUTH_CAPTURE


def test_methods_that_cannot_hold_still_fall_back(monkeypatch):
    """Bank transfer and USSD take the money or they do not."""
    monkeypatch.setattr("app.payments.preauth.preauth_enabled", lambda: True)
    for method in ("bank_transfer", "mobile_money", "wallet", "something_new", None):
        assert (
            capture_model_for(method, settles_later=True) is CaptureModel.CHARGE_REFUND
        ), method


def test_every_model_tells_the_buyer_what_will_happen():
    """Under CHARGE_REFUND their money leaves and comes back. Finding that out
    afterwards feels like our mistake even when it is what was supposed to
    happen."""
    for model in CaptureModel:
        text = describe_for_buyer(model, 50_000)
        assert "₦500.00" in text
    assert "hold" in describe_for_buyer(CaptureModel.PREAUTH_CAPTURE, 50_000)
    assert "refund" in describe_for_buyer(CaptureModel.CHARGE_REFUND, 50_000)


def test_a_hold_is_assumed_good_for_the_short_end_of_the_window():
    """Paystack says 5-10 days depending on the issuer. Assuming the generous
    end is how a hold lapses unnoticed."""
    from datetime import datetime, timedelta

    now = datetime(2026, 1, 1)
    assert hold_expires_at(now) == now + timedelta(days=5)


# ---------------------------------------------------------------------------
# Logistics boundary
# ---------------------------------------------------------------------------


def _job():
    return JobRequest(
        order_id="ORD_1",
        pickup_lat=7.41,
        pickup_lng=3.90,
        pickup_contact="Amaka Fabrics",
        dropoff_lat=7.44,
        dropoff_lng=3.89,
        dropoff_contact="Amaka Obi",
        dropoff_phone="08012345678",
        item_count=1,
        total_weight_grams=500,
        fee_minor=50_000,
    )


def test_the_internal_fleet_is_the_default():
    assert get_adapter().name == "internal"


def test_an_unknown_adapter_falls_back_rather_than_failing_the_order():
    """The buyer has already paid. A misconfigured adapter name must not be
    the thing that strands them."""
    assert get_adapter("no_such_provider").name == "internal"


def test_the_partner_stub_marks_its_own_jobs():
    """A stub that looks like production is how a stub reaches production."""
    job = PartnerStubAdapter().create_job(_job())
    assert job.reference.startswith("STUB-")
    assert job.provider == "partner_stub"


def test_a_real_partner_adapter_slots_in_without_touching_callers():
    class AffiliatePartner:
        name = "affiliate"

        def create_job(self, request):
            from app.delivery_pricing.logistics import DeliveryJob

            return DeliveryJob(reference="AFF-99", provider=self.name)

    register_adapter(AffiliatePartner)
    assert get_adapter("affiliate").create_job(_job()).reference == "AFF-99"


@pytest.mark.parametrize(
    "provider_word,expected",
    [
        ("assigned", DeliveryState.ASSIGNED),
        ("accepted", DeliveryState.ASSIGNED),
        ("PICKED_UP", DeliveryState.PICKED_UP),
        ("collected", DeliveryState.PICKED_UP),
        ("en_route", DeliveryState.IN_TRANSIT),
        ("completed", DeliveryState.DELIVERED),
    ],
)
def test_provider_vocabulary_maps_to_ours(provider_word, expected):
    """A partner sends their own words. They become ours in one place, so
    nothing downstream has to know which provider a status came from."""
    d = _delivery(DeliveryState.JOB_CREATED)
    if expected in (
        DeliveryState.PICKED_UP,
        DeliveryState.IN_TRANSIT,
        DeliveryState.DELIVERED,
    ):
        d.transition_to(DeliveryState.ASSIGNED)
        if expected is not DeliveryState.PICKED_UP:
            d.transition_to(DeliveryState.PICKED_UP)
        if expected is DeliveryState.DELIVERED:
            d.transition_to(DeliveryState.IN_TRANSIT)
    assert apply_status(d, provider_word) is True
    assert d.state is expected


def test_an_unrecognised_status_is_ignored_not_raised():
    """A courier webhook with a word we do not know is not an incident."""
    d = _delivery(DeliveryState.JOB_CREATED)
    assert apply_status(d, "teleported") is False
    assert d.state is DeliveryState.JOB_CREATED


def test_a_duplicate_webhook_is_a_no_op():
    """Retries are normal traffic. 500ing at them makes couriers retry
    harder."""
    d = _delivery(DeliveryState.ASSIGNED)
    assert apply_status(d, "assigned") is False
    assert d.state is DeliveryState.ASSIGNED


def test_an_out_of_order_webhook_does_not_rewind_the_parcel():
    """Webhooks arrive out of order. A late "assigned" after "picked_up" must
    not move the parcel backwards."""
    d = _delivery(DeliveryState.PICKED_UP)
    assert apply_status(d, "assigned") is False
    assert d.state is DeliveryState.PICKED_UP


def test_a_failure_reason_is_recorded():
    d = _delivery(DeliveryState.ASSIGNED)
    assert apply_status(d, "failed", reason="Nobody at the address") is True
    assert d.failure_reason == "Nobody at the address"


def test_preauth_is_off_unless_the_environment_says_otherwise(monkeypatch):
    """The default itself, not a monkeypatched stand-in for it.

    Paystack gates pre-authorization per merchant, so whether it works cannot
    be inferred from the API — someone has to tell us. Defaulting to on means
    attempting a hold on an account without it, which produces a plain charge:
    the buyer is charged the ceiling having been told it would only be held.
    That is the worst outcome in this file, so the default is the thing worth
    a test of its own.
    """
    from importlib import reload

    import app.payments.preauth as preauth_module

    monkeypatch.delenv("PAYSTACK_PREAUTH_ENABLED", raising=False)
    reload(preauth_module)
    assert preauth_module.preauth_enabled() is False
    assert (
        preauth_module.capture_model_for("card", settles_later=True)
        is preauth_module.CaptureModel.CHARGE_REFUND
    )
