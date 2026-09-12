"""Wiring a delivery quote into checkout.

Pure tests: no database. The order transaction itself is exercised by the
DB-backed suite; what matters here is the boundary work that a schema change
or a refactor can quietly break -- the kobo/naira conversion, the field-for-
field snapshot, and the guard that stops one quote paying for two journeys.
"""

from decimal import Decimal

import pytest

from app.cart.services import CartService
from app.libs.errors import ValidationError
from app.libs.money import from_subunit, to_subunit


# --- the kobo/naira boundary -----------------------------------------------


@pytest.mark.parametrize(
    "minor,naira",
    [
        (0, "0.00"),
        (1, "0.01"),
        (50_000, "500.00"),
        (70_000, "700.00"),
        (123_456, "1234.56"),
        (999_999_999, "9999999.99"),
    ],
)
def test_kobo_becomes_exactly_the_naira_it_should(minor, naira):
    assert from_subunit(minor) == Decimal(naira)


def test_a_fee_survives_the_round_trip_unchanged():
    # The property that matters: a fee quoted in kobo, stored as naira on the
    # order and sent back to Paystack in kobo must be the same number at both
    # ends. A kobo lost here is a kobo nobody can account for later.
    for minor in (1, 7, 99, 100, 101, 50_000, 70_001, 1_234_567):
        assert to_subunit(from_subunit(minor)) == minor


def test_no_fee_is_still_no_fee():
    assert from_subunit(None) is None


def test_a_bool_is_not_an_amount_of_money():
    # bool subclasses int, so `from_subunit(True)` would otherwise mean one
    # kobo. That is never what any caller meant, and it is the kind of thing
    # that arrives from a JSON body.
    with pytest.raises(TypeError):
        from_subunit(True)


def test_a_float_is_not_minor_units():
    # Minor units are integers by definition. A float here means someone
    # passed naira to the function that expects kobo -- 700.0 would silently
    # become ₦7.00 instead of ₦700.00.
    with pytest.raises(TypeError):
        from_subunit(700.0)


# --- the snapshot -----------------------------------------------------------


class _Seller:
    def __init__(self, market_id):
        self.market_id = market_id


class _Product:
    def __init__(self, market_id):
        self.seller = _Seller(market_id)


class _Item:
    def __init__(self, market_id):
        self.product = _Product(market_id)


class _Cart:
    def __init__(self, *market_ids):
        self.items = [_Item(m) for m in market_ids]


class _Order:
    id = "ORD_TEST_1"


class _Quote:
    id = "QT_1"
    fee_minor = 70_000
    breakdown = {"lines": [{"label": "Base", "amount_minor": 50_000}]}
    distance_km = 4.2
    strategy = "zone_band"
    strategy_version = "1.0.0"
    pickup_lat = 7.4188
    pickup_lng = 3.9060
    dropoff_lat = 7.4441
    dropoff_lng = 3.8964


class _Session:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


@pytest.fixture
def consumed_quote(monkeypatch):
    """Stand in for the DB-backed consume, which has its own tests."""
    from app.delivery_pricing import services as quote_services

    monkeypatch.setattr(
        quote_services.QuoteService,
        "consume",
        staticmethod(lambda session, quote_id, buyer_id, order_id: _Quote()),
    )
    return _Quote()


def _attach(session, cart, *, batch_opt_in=False):
    return CartService._attach_delivery(
        session,
        _Order(),
        cart,
        quote_id="QT_1",
        buyer_id=1,
        batch_opt_in=batch_opt_in,
    )


def test_the_order_is_charged_the_fee_that_was_quoted(consumed_quote):
    fee = _attach(_Session(), _Cart("mkt_a"))
    assert fee == Decimal("700.00")


def test_every_field_of_the_quote_is_copied_onto_the_order(consumed_quote):
    session = _Session()
    _attach(session, _Cart("mkt_a"))

    (delivery,) = session.added
    # Field for field, because a snapshot that silently drops one is a
    # six-month-old order that can no longer explain its own fee.
    assert delivery.quote_id == _Quote.id
    assert delivery.fee_minor == _Quote.fee_minor
    assert delivery.breakdown == _Quote.breakdown
    assert delivery.distance_km == _Quote.distance_km
    assert delivery.strategy == _Quote.strategy
    assert delivery.strategy_version == _Quote.strategy_version
    assert delivery.pickup_lat == _Quote.pickup_lat
    assert delivery.pickup_lng == _Quote.pickup_lng
    assert delivery.dropoff_lat == _Quote.dropoff_lat
    assert delivery.dropoff_lng == _Quote.dropoff_lng


def test_the_solo_price_is_recorded_even_when_going_solo(consumed_quote):
    # Recorded at checkout because after a batch closes there is no way to
    # reconstruct what going alone would have cost -- and that number is the
    # ceiling a shared fee is capped at.
    session = _Session()
    _attach(session, _Cart("mkt_a"), batch_opt_in=True)
    (delivery,) = session.added
    assert delivery.solo_fee_minor == _Quote.fee_minor


def test_nobody_is_put_in_a_batch_without_asking(consumed_quote):
    session = _Session()
    _attach(session, _Cart("mkt_a"))
    (delivery,) = session.added
    assert delivery.batch_opt_in is False


def test_opting_in_is_carried_through(consumed_quote):
    session = _Session()
    _attach(session, _Cart("mkt_a"), batch_opt_in=True)
    (delivery,) = session.added
    assert delivery.batch_opt_in is True


# --- the guard --------------------------------------------------------------


def test_one_quote_cannot_pay_for_two_markets(consumed_quote):
    # Two markets is two delivery runs. Accepting a single quote would charge
    # the buyer for one journey and leave Markt paying for the other.
    session = _Session()
    with pytest.raises(ValidationError):
        _attach(session, _Cart("mkt_a", "mkt_b"))
    assert session.added == [], "no delivery row should survive the refusal"


def test_a_seller_with_no_market_still_counts_as_a_journey(consumed_quote):
    # An unresolved seller is not a free delivery. One real market plus one
    # unknown is still two runs, so a single quote must not cover it.
    session = _Session()
    with pytest.raises(ValidationError):
        _attach(session, _Cart("mkt_a", None))


def test_a_single_market_basket_is_fine(consumed_quote):
    # Several items, one market: one journey, one quote.
    fee = _attach(_Session(), _Cart("mkt_a", "mkt_a", "mkt_a"))
    assert fee == Decimal("700.00")
