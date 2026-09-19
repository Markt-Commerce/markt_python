"""Advancing a delivery once the money is good.

A delivery used to be created at QUOTED and stay there forever: nothing moved
its state, and nothing ever asked a courier to carry the parcel. These cover
the two halves of that -- marking paid inside the payment's transaction, and
creating the job after it commits.
"""

from contextlib import contextmanager

import pytest

from app.delivery_pricing import dispatch as dispatch_module
from app.delivery_pricing.dispatch import _job_request_for, dispatch, mark_paid
from app.delivery_pricing.order_delivery import DeliveryState, OrderDelivery


def _delivery(state=DeliveryState.QUOTED, **kw):
    d = OrderDelivery()
    d.order_id = kw.get("order_id", "ORD_D1")
    d.state = state
    d.fee_minor = kw.get("fee_minor", 70_000)
    d.solo_fee_minor = kw.get("solo_fee_minor", 70_000)
    d.settled_fee_minor = kw.get("settled_fee_minor")
    d.pickup_lat, d.pickup_lng = 7.4305, 3.9047
    d.dropoff_lat, d.dropoff_lng = 7.4441, 3.8964
    d.external_job_id = kw.get("external_job_id")
    if "order" in kw:
        # Straight into the instance dict: assigning to the relationship goes
        # through SQLAlchemy's instrumentation, which wants a real mapped
        # object. dispatch() only ever reads it.
        d.__dict__["order"] = kw["order"]
    return d


class _Query:
    def __init__(self, result):
        self._result = result

    def filter_by(self, **kw):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self._result


class _Session:
    def __init__(self, result=None):
        self._result = result

    def query(self, *a, **kw):
        return _Query(self._result)


# --- mark_paid --------------------------------------------------------------


def test_a_paid_order_moves_its_delivery_to_paid():
    d = _delivery()
    assert mark_paid(_Session(d), "ORD_D1") is d
    assert d.state is DeliveryState.PAID


def test_an_order_with_no_delivery_is_not_an_error():
    # Checking out without a quote is legitimate and leaves no delivery row.
    assert mark_paid(_Session(None), "ORD_D1") is None


def test_completing_the_same_payment_twice_does_not_rewind_the_parcel():
    """Paystack's webhook and the browser callback both land, by design."""
    for state in (
        DeliveryState.PAID,
        DeliveryState.JOB_CREATED,
        DeliveryState.PICKED_UP,
        DeliveryState.DELIVERED,
    ):
        d = _delivery(state=state)
        mark_paid(_Session(d), "ORD_D1")
        assert d.state is state, state


def test_marking_paid_never_raises_into_a_payment(monkeypatch):
    """The money is already taken. An exception here would fail a completion
    that has no business failing."""

    class _Exploding:
        def query(self, *a, **kw):
            raise RuntimeError("database went away")

    assert mark_paid(_Exploding(), "ORD_D1") is None


# --- dispatch ---------------------------------------------------------------


@contextmanager
def _scope(session):
    yield session


class _Job:
    def __init__(self, reference="JOB-1", provider="test"):
        self.reference = reference
        self.provider = provider


def _patch_scope(monkeypatch, session):
    monkeypatch.setattr(dispatch_module, "session_scope", lambda: _scope(session))


def _patch_adapter(monkeypatch, adapter):
    monkeypatch.setattr(dispatch_module, "get_adapter", lambda *a, **kw: adapter)


class _GoodAdapter:
    name = "test"

    def __init__(self):
        self.calls = []

    def create_job(self, request):
        self.calls.append(request)
        return _Job()


class _RefusingAdapter:
    name = "refusing"

    def create_job(self, request):
        raise RuntimeError("their API is down")


def test_a_paid_delivery_becomes_a_courier_job(monkeypatch):
    d = _delivery(state=DeliveryState.PAID, order=_Order())
    _patch_scope(monkeypatch, _Session(d))
    adapter = _GoodAdapter()
    _patch_adapter(monkeypatch, adapter)

    assert dispatch("ORD_D1") is True
    assert d.state is DeliveryState.JOB_CREATED
    assert d.external_job_id == "JOB-1"
    assert len(adapter.calls) == 1


def test_a_provider_refusing_never_loses_the_order(monkeypatch):
    """The buyer has paid and is owed a delivery. It parks where an operator
    can see it rather than pretending dispatch worked."""
    d = _delivery(state=DeliveryState.PAID, order=_Order())
    _patch_scope(monkeypatch, _Session(d))
    _patch_adapter(monkeypatch, _RefusingAdapter())

    assert dispatch("ORD_D1") is False
    assert d.state is DeliveryState.AWAITING_DISPATCH


def test_a_second_webhook_cannot_create_a_second_courier_job(monkeypatch):
    d = _delivery(
        state=DeliveryState.JOB_CREATED, external_job_id="JOB-1", order=_Order()
    )
    _patch_scope(monkeypatch, _Session(d))
    adapter = _GoodAdapter()
    _patch_adapter(monkeypatch, adapter)

    assert dispatch("ORD_D1") is False
    assert adapter.calls == []
    assert d.external_job_id == "JOB-1"


def test_an_unpaid_delivery_is_not_dispatched(monkeypatch):
    d = _delivery(state=DeliveryState.QUOTED, order=_Order())
    _patch_scope(monkeypatch, _Session(d))
    adapter = _GoodAdapter()
    _patch_adapter(monkeypatch, adapter)

    assert dispatch("ORD_D1") is False
    assert adapter.calls == []


# --- what the provider is told ---------------------------------------------


class _Seller:
    shop_name = "Amaka Fabrics"


class _Item:
    quantity = 3
    seller = _Seller()


class _Address:
    recipient_name = "Amaka Obi"


class _User:
    phone_number = "+2348087654321"


class _Buyer:
    user = _User()


class _Order:
    id = "ORD_D1"
    items = [_Item(), _Item()]
    shipping_address = _Address()
    buyer = _Buyer()
    customer_note = "Gate 2"


def test_the_provider_is_told_where_the_parcel_was_priced_to_go():
    # From the snapshot, not re-resolved: re-deriving it now could send a
    # rider somewhere the buyer was never charged for.
    d = _delivery(state=DeliveryState.PAID)
    req = _job_request_for(d, _Order())
    assert (req.pickup_lat, req.pickup_lng) == (7.4305, 3.9047)
    assert (req.dropoff_lat, req.dropoff_lng) == (7.4441, 3.8964)


def test_the_provider_gets_contacts_and_a_fee_but_no_buyer_identity():
    req = _job_request_for(_delivery(state=DeliveryState.PAID), _Order())
    assert req.pickup_contact == "Amaka Fabrics"
    assert req.dropoff_contact == "Amaka Obi"
    assert req.dropoff_phone == "+2348087654321"
    assert req.item_count == 6
    assert req.fee_minor == 70_000
    # Nothing identifying beyond a name and a number to call.
    assert not hasattr(req, "buyer_id")
    assert not hasattr(req, "email")


def test_a_settled_batch_fee_is_what_the_provider_is_paid():
    # effective_fee_minor, not the solo quote: once a batch settles, the
    # settled number is the real one.
    d = _delivery(state=DeliveryState.PAID, solo_fee_minor=70_000)
    d.settled_fee_minor = 40_000
    assert _job_request_for(d, _Order()).fee_minor == 40_000


def test_a_missing_recipient_name_does_not_stop_a_delivery():
    class _Nameless(_Order):
        shipping_address = None
        buyer = None

    req = _job_request_for(_delivery(state=DeliveryState.PAID), _Nameless())
    assert req.dropoff_contact == "Markt customer"
    assert req.dropoff_phone is None


# --- the inbound webhook's signature ---------------------------------------


def _sign(body: bytes, secret: str) -> str:
    import hashlib
    import hmac as _hmac

    return _hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()


def test_a_correctly_signed_status_is_accepted(monkeypatch):
    from app.delivery_pricing import routes

    monkeypatch.setattr(routes, "config", lambda *a, **kw: "shared-secret")
    body = b'{"status":"picked_up"}'
    assert routes._signature_is_valid(body, _sign(body, "shared-secret")) is True


def test_a_status_signed_with_the_wrong_secret_is_refused(monkeypatch):
    from app.delivery_pricing import routes

    monkeypatch.setattr(routes, "config", lambda *a, **kw: "shared-secret")
    body = b'{"status":"picked_up"}'
    assert routes._signature_is_valid(body, _sign(body, "guessed")) is False


def test_a_tampered_body_is_refused(monkeypatch):
    """The signature covers the raw body, so changing the parcel's fate after
    signing it must not verify."""
    from app.delivery_pricing import routes

    monkeypatch.setattr(routes, "config", lambda *a, **kw: "shared-secret")
    signature = _sign(b'{"status":"failed"}', "shared-secret")
    assert routes._signature_is_valid(b'{"status":"delivered"}', signature) is False


def test_with_no_secret_configured_nothing_is_accepted(monkeypatch):
    """No secret means no partner is sending us anything yet. An open endpoint
    that moves parcels through their states is worth more to an attacker than
    it is to us, so it refuses rather than waves things through."""
    from app.delivery_pricing import routes

    monkeypatch.setattr(routes, "config", lambda *a, **kw: "")
    body = b'{"status":"delivered"}'
    assert routes._signature_is_valid(body, _sign(body, "")) is False
    assert routes._signature_is_valid(body, "") is False


def test_an_empty_signature_is_refused(monkeypatch):
    from app.delivery_pricing import routes

    monkeypatch.setattr(routes, "config", lambda *a, **kw: "shared-secret")
    assert routes._signature_is_valid(b'{"status":"delivered"}', "") is False


# --- cancellation -----------------------------------------------------------


def test_cancelling_before_a_rider_has_it_is_fine():
    from app.delivery_pricing.dispatch import cancel_for_order

    for state in (
        DeliveryState.QUOTED,
        DeliveryState.PAID,
        DeliveryState.AWAITING_DISPATCH,
        DeliveryState.JOB_CREATED,
        DeliveryState.ASSIGNED,
        DeliveryState.FAILED,
    ):
        d = _delivery(state=state)
        assert cancel_for_order(_Session(d), "ORD_D1") is d
        assert d.state is DeliveryState.CANCELLED, state


def test_cancelling_once_the_parcel_is_moving_is_refused():
    """Past pickup this is a return, not a cancellation: a rider has to carry
    it back, which costs real money. Refunding the delivery fee for a journey
    somebody actually made is money we do not get back."""
    from app.libs.errors import ValidationError
    from app.delivery_pricing.dispatch import cancel_for_order

    for state in (
        DeliveryState.PICKED_UP,
        DeliveryState.IN_TRANSIT,
        DeliveryState.DELIVERED,
    ):
        d = _delivery(state=state)
        with pytest.raises(ValidationError):
            cancel_for_order(_Session(d), "ORD_D1")
        assert d.state is state, state


def test_cancelling_an_order_with_no_delivery_is_not_an_error():
    from app.delivery_pricing.dispatch import cancel_for_order

    assert cancel_for_order(_Session(None), "ORD_D1") is None


def test_cancelling_twice_is_not_an_error():
    from app.delivery_pricing.dispatch import cancel_for_order

    d = _delivery(state=DeliveryState.CANCELLED)
    assert cancel_for_order(_Session(d), "ORD_D1") is d
    assert d.state is DeliveryState.CANCELLED
