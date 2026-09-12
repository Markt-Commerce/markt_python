"""Serviceability gating and quote consumption, against a real database.

The two things worth proving here cannot be proven with a mocked session: that
an empty registry means "we deliver nowhere" rather than "we deliver
everywhere", and that consuming a quote is safe when two checkout submissions
arrive at once.

Gated on RUN_DB_TESTS=1 like the other real-database tests.
"""

import os
import threading
import uuid
from datetime import datetime, timedelta

import pytest

from app.delivery_pricing.models import (
    DeliveryLane,
    DeliveryQuote,
    QuoteStatus,
    ServiceCity,
    ServiceZone,
)
from app.delivery_pricing.services import (
    NotServiceable,
    QuoteExpired,
    QuoteService,
    ServiceabilityService,
)
from app.libs.errors import ConflictError, NotFoundError
from app.orders.models import Order, OrderStatus
from app.users.models import Buyer, User
from external.database import db
from main.setup import create_flask_app

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason=(
        "requires a disposable database; set RUN_DB_TESTS=1 only when DB_* "
        "points at a throwaway Postgres instance"
    ),
)

# Real places, so the distances are checkable against a map.
BODIJA = (7.4188, 3.9060)
UI_CAMPUS = (7.4441, 3.8964)  # ~3.2 km from Bodija
IKEJA = (6.6018, 3.3515)  # another city entirely


@pytest.fixture(scope="module")
def app():
    flask_app = create_flask_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def world(app):
    """A city with two zones and one lane, removed afterwards."""
    marker = uuid.uuid4().hex[:8]
    made = {"quotes": [], "lanes": [], "zones": [], "cities": [], "users": []}

    with app.app_context():
        city = ServiceCity(
            name=f"Ibadan {marker}", slug=f"ibadan-{marker}", is_active=True
        )
        db.session.add(city)
        db.session.flush()

        bodija = ServiceZone(
            city_id=city.id,
            name=f"Bodija {marker}",
            slug=f"bodija-{marker}",
            centroid_lat=BODIJA[0],
            centroid_lng=BODIJA[1],
            radius_km=3.0,
        )
        ui = ServiceZone(
            city_id=city.id,
            name=f"UI {marker}",
            slug=f"ui-{marker}",
            centroid_lat=UI_CAMPUS[0],
            centroid_lng=UI_CAMPUS[1],
            radius_km=3.0,
        )
        db.session.add_all([bodija, ui])
        db.session.flush()

        lane = DeliveryLane(from_zone_id=bodija.id, to_zone_id=ui.id, is_active=True)
        db.session.add(lane)

        user = User(
            email=f"quote-{marker}@markt.test", username=f"q{marker}", is_buyer=True
        )
        user.set_password("Passw0rdy")
        db.session.add(user)
        db.session.flush()
        buyer = Buyer(user_id=user.id, buyername="Amaka Obi")
        db.session.add(buyer)
        db.session.flush()

        # Real orders: order_id is a foreign key, and consuming a quote onto
        # an id that does not exist is not a case that can happen.
        orders = []
        for _ in range(3):
            o = Order(buyer_id=buyer.id, status=OrderStatus.PENDING_PAYMENT)
            db.session.add(o)
            db.session.flush()
            orders.append(o.id)
        db.session.commit()

        made.update(
            city_id=city.id,
            bodija_id=bodija.id,
            ui_id=ui.id,
            lane_id=lane.id,
            buyer_id=buyer.id,
            user_id=user.id,
            orders=orders,
        )

    yield made

    with app.app_context():
        db.session.query(DeliveryQuote).filter(
            DeliveryQuote.buyer_id == made["buyer_id"]
        ).delete(synchronize_session=False)
        db.session.query(DeliveryLane).filter(
            DeliveryLane.id == made["lane_id"]
        ).delete(synchronize_session=False)
        db.session.query(ServiceZone).filter(
            ServiceZone.city_id == made["city_id"]
        ).delete(synchronize_session=False)
        db.session.query(ServiceCity).filter(ServiceCity.id == made["city_id"]).delete(
            synchronize_session=False
        )
        db.session.query(Order).filter(Order.buyer_id == made["buyer_id"]).delete(
            synchronize_session=False
        )
        db.session.query(Buyer).filter(Buyer.id == made["buyer_id"]).delete()
        db.session.query(User).filter(User.id == made["user_id"]).delete()
        db.session.commit()


# ---------------------------------------------------------------------------
# Serviceability
# ---------------------------------------------------------------------------


def test_a_served_route_quotes(app, world):
    with app.app_context():
        quote = QuoteService.create(
            buyer_id=world["buyer_id"], pickup=BODIJA, dropoff=UI_CAMPUS
        )
        assert quote.fee_minor > 0
        assert quote.distance_km == pytest.approx(3.2, abs=0.5)
        assert quote.breakdown["total_minor"] == quote.fee_minor


def test_an_unserved_city_is_refused_by_name(app, world):
    """The reason has to say which end is the problem. "Delivery unavailable"
    with no subject is how someone re-enters a perfectly good address."""
    with app.app_context(), pytest.raises(NotServiceable) as caught:
        QuoteService.create(buyer_id=world["buyer_id"], pickup=BODIJA, dropoff=IKEJA)
    assert caught.value.payload["reason"] == "dropoff_not_serviceable"


def test_an_unserved_pickup_is_refused_separately(app, world):
    with app.app_context(), pytest.raises(NotServiceable) as caught:
        QuoteService.create(buyer_id=world["buyer_id"], pickup=IKEJA, dropoff=UI_CAMPUS)
    assert caught.value.payload["reason"] == "pickup_not_serviceable"


def test_two_served_zones_with_no_lane_are_refused(app, world):
    """Both ends serviceable is not the same as a route we run. Quoting a fee
    for a lane no rider takes is worse than saying no."""
    with app.app_context():
        db.session.query(DeliveryLane).filter(
            DeliveryLane.id == world["lane_id"]
        ).update({DeliveryLane.is_active: False})
        db.session.commit()

    with app.app_context(), pytest.raises(NotServiceable) as caught:
        QuoteService.create(
            buyer_id=world["buyer_id"], pickup=BODIJA, dropoff=UI_CAMPUS
        )
    assert caught.value.payload["reason"] == "no_lane"

    with app.app_context():
        db.session.query(DeliveryLane).filter(
            DeliveryLane.id == world["lane_id"]
        ).update({DeliveryLane.is_active: True})
        db.session.commit()


def test_an_inactive_city_takes_its_zones_with_it(app, world):
    """Pausing a city must stop delivery in it, without editing every zone."""
    with app.app_context():
        db.session.query(ServiceCity).filter(ServiceCity.id == world["city_id"]).update(
            {ServiceCity.is_active: False}
        )
        db.session.commit()

    with app.app_context(), pytest.raises(NotServiceable):
        QuoteService.create(
            buyer_id=world["buyer_id"], pickup=BODIJA, dropoff=UI_CAMPUS
        )

    with app.app_context():
        db.session.query(ServiceCity).filter(ServiceCity.id == world["city_id"]).update(
            {ServiceCity.is_active: True}
        )
        db.session.commit()


def test_a_missing_seller_location_is_named_as_such(app, world):
    """Most sellers had no coordinates until recently. "This shop hasn't set
    its location" is actionable; "not serviceable" sends the buyer hunting for
    a fault in their own address."""
    with app.app_context(), pytest.raises(NotServiceable) as caught:
        QuoteService.create(
            buyer_id=world["buyer_id"], pickup=(None, None), dropoff=UI_CAMPUS
        )
    assert caught.value.payload["reason"] == "pickup_unlocated"


def test_zero_zero_is_not_a_location(app, world):
    """(0, 0) is what a failed geocode looks like, not a shop in the Gulf of
    Guinea."""
    with app.app_context(), pytest.raises(NotServiceable) as caught:
        QuoteService.create(
            buyer_id=world["buyer_id"], pickup=(0.0, 0.0), dropoff=UI_CAMPUS
        )
    assert caught.value.payload["reason"] == "pickup_unlocated"


# ---------------------------------------------------------------------------
# Consumption
# ---------------------------------------------------------------------------


def test_a_quote_is_consumed_once(app, world):
    with app.app_context():
        quote = QuoteService.create(
            buyer_id=world["buyer_id"], pickup=BODIJA, dropoff=UI_CAMPUS
        )
    with app.app_context():
        consumed = QuoteService.consume(
            db.session, quote.id, world["buyer_id"], world["orders"][0]
        )
        assert consumed.status == QuoteStatus.CONSUMED
        db.session.commit()

    with app.app_context(), pytest.raises(ConflictError):
        QuoteService.consume(
            db.session, quote.id, world["buyer_id"], world["orders"][1]
        )
        db.session.commit()


def test_replaying_the_same_checkout_is_idempotent(app, world):
    """A network retry must not look like a second order trying to steal a
    quote."""
    with app.app_context():
        quote = QuoteService.create(
            buyer_id=world["buyer_id"], pickup=BODIJA, dropoff=UI_CAMPUS
        )
    with app.app_context():
        QuoteService.consume(
            db.session, quote.id, world["buyer_id"], world["orders"][0]
        )
        db.session.commit()
    with app.app_context():
        again = QuoteService.consume(
            db.session, quote.id, world["buyer_id"], world["orders"][0]
        )
        assert again.status == QuoteStatus.CONSUMED


def test_an_expired_quote_cannot_be_consumed(app, world):
    """The fee shown at cart must never be the fee charged an hour later."""
    with app.app_context():
        quote = QuoteService.create(
            buyer_id=world["buyer_id"], pickup=BODIJA, dropoff=UI_CAMPUS
        )
    with app.app_context():
        db.session.query(DeliveryQuote).filter(DeliveryQuote.id == quote.id).update(
            {DeliveryQuote.expires_at: datetime.utcnow() - timedelta(seconds=1)}
        )
        db.session.commit()

    with app.app_context(), pytest.raises(QuoteExpired):
        QuoteService.consume(
            db.session, quote.id, world["buyer_id"], world["orders"][0]
        )


def test_another_buyers_quote_is_not_found_rather_than_forbidden(app, world):
    """Telling someone a quote exists but is not theirs is more than they need
    to know."""
    with app.app_context():
        quote = QuoteService.create(
            buyer_id=world["buyer_id"], pickup=BODIJA, dropoff=UI_CAMPUS
        )
    with app.app_context(), pytest.raises(NotFoundError):
        QuoteService.consume(
            db.session, quote.id, world["buyer_id"] + 99_999, world["orders"][0]
        )


def test_two_simultaneous_checkouts_cannot_both_claim_one_quote(app, world):
    """The race the row lock exists for.

    A double-tap on "Pay" sends two checkout submissions milliseconds apart.
    Without `with_for_update`, both read an ACTIVE quote, both write CONSUMED,
    and the second order rides on a delivery fee it never reserved.

    Firing two threads at once does *not* test this -- they rarely overlap, and
    the second usually reads after the first has committed, so the test passes
    with the lock removed. (It did. That is why it is written this way.)

    So the overlap is forced: a holder thread takes the row lock and sits on it
    while the claimer calls consume. With the lock, the claimer blocks until
    the holder commits and then correctly sees a consumed quote. Without it,
    the claimer reads straight past the held row and claims it.
    """
    from app.delivery_pricing.models import DeliveryQuote as Q

    with app.app_context():
        quote = QuoteService.create(
            buyer_id=world["buyer_id"], pickup=BODIJA, dropoff=UI_CAMPUS
        )
        quote_id = quote.id

    holding = threading.Event()
    released = threading.Event()

    def hold_the_row():
        with app.app_context():
            try:
                row = (
                    db.session.query(Q)
                    .filter(Q.id == quote_id)
                    .with_for_update()
                    .first()
                )
                holding.set()
                # Long enough that an unlocked claimer will certainly have
                # read and written before this commits.
                released.wait(timeout=5)
                row.status = QuoteStatus.CONSUMED
                row.order_id = world["orders"][0]
                db.session.commit()
            finally:
                db.session.remove()

    outcome = {}

    def claim():
        holding.wait(timeout=5)
        # Give the claimer a moment to get as far as its own SELECT, then let
        # the holder finish. If consume locks, the claimer is still waiting
        # here; if it does not, it has already read stale state.
        with app.app_context():
            try:
                threading.Timer(0.5, released.set).start()
                QuoteService.consume(
                    db.session, quote_id, world["buyer_id"], world["orders"][1]
                )
                db.session.commit()
                outcome["result"] = "claimed"
            except ConflictError:
                db.session.rollback()
                outcome["result"] = "refused"
            except Exception as exc:
                db.session.rollback()
                outcome["result"] = f"error: {exc!r}"
            finally:
                db.session.remove()

    holder = threading.Thread(target=hold_the_row)
    claimer = threading.Thread(target=claim)
    holder.start()
    claimer.start()
    holder.join(timeout=15)
    claimer.join(timeout=15)

    assert outcome.get("result") == "refused", (
        "the second checkout claimed a quote the first had already taken — "
        f"got {outcome.get('result')!r}"
    )

    with app.app_context():
        final = db.session.query(Q).filter(Q.id == quote_id).first()
        assert final.order_id == world["orders"][0]
