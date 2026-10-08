"""A buyer's request reaches sellers who could actually deliver it.

Markt does not deliver between cities -- a lane across two returns no_lane by
design -- so a request that fanned out to every matching seller in the country
told a seller in Lagos about a buyer in Ibadan they can never sell to, and
spent the buyer's request on people who could not answer it.

Only a REROUTE_ENGINE request carries a market_id, and that filter never
applied to the ones buyers actually post.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.requests.services import BuyerRequestService


def _seller(sid, lat, lng):
    return SimpleNamespace(
        id=sid, user_id=f"USR_{sid}", shop_latitude=lat, shop_longitude=lng
    )


def _request(user_id="USR_buyer"):
    return SimpleNamespace(id="REQ_1", user_id=user_id, title="A jersey")


def _run(
    sellers,
    buyer_city,
    seller_cities,
    address=SimpleNamespace(latitude=7.4, longitude=3.9),
):
    """city_id_for_point answers for the buyer first, then per seller."""
    session = MagicMock()
    chain = session.query.return_value.filter.return_value.order_by.return_value
    chain.first.return_value = address

    def city_for(_session, lat, lng):
        if address is not None and (lat, lng) == (address.latitude, address.longitude):
            return buyer_city
        return seller_cities.get((lat, lng))

    with patch("app.delivery_pricing.services.city_id_for_point", side_effect=city_for):
        return BuyerRequestService._sellers_in_buyers_city(session, _request(), sellers)


def test_a_seller_in_another_city_is_not_told():
    """The case this exists for: they cannot deliver it."""
    near = _seller("near", 7.41, 3.91)
    far = _seller("far", 6.52, 3.37)
    kept = _run(
        [near, far], buyer_city=1, seller_cities={(7.41, 3.91): 1, (6.52, 3.37): 2}
    )
    assert kept == [near]


def test_sellers_in_the_same_city_are_all_kept():
    a, b = _seller("a", 7.41, 3.91), _seller("b", 7.44, 3.95)
    kept = _run([a, b], buyer_city=1, seller_cities={(7.41, 3.91): 1, (7.44, 3.95): 1})
    assert kept == [a, b]


def test_a_buyer_with_no_address_still_reaches_sellers():
    """Unscoped is wrong; silence is worse. A request nobody hears is a dead
    feature, so an unknown location falls back rather than filtering to none."""
    a = _seller("a", 7.41, 3.91)
    kept = _run([a], buyer_city=1, seller_cities={}, address=None)
    assert kept == [a]


def test_a_buyer_outside_any_serviceable_city_still_reaches_sellers():
    a = _seller("a", 7.41, 3.91)
    kept = _run([a], buyer_city=None, seller_cities={(7.41, 3.91): 1})
    assert kept == [a]


def test_when_no_seller_is_local_the_request_is_not_silenced():
    """Better a seller who cannot deliver today than a request that reaches
    nobody -- the fallback is deliberate, not an oversight."""
    far = _seller("far", 6.52, 3.37)
    kept = _run([far], buyer_city=1, seller_cities={(6.52, 3.37): 2})
    assert kept == [far]


def test_a_seller_with_no_shop_location_is_not_assumed_local():
    unplaced = SimpleNamespace(
        id="u", user_id="USR_u", shop_latitude=None, shop_longitude=None
    )
    near = _seller("near", 7.41, 3.91)
    kept = _run([unplaced, near], buyer_city=1, seller_cities={(7.41, 3.91): 1})
    assert kept == [near]


def test_a_request_with_no_author_is_left_alone():
    session = MagicMock()
    sellers = [_seller("a", 7.41, 3.91)]
    got = BuyerRequestService._sellers_in_buyers_city(
        session, SimpleNamespace(id="REQ_1", title="x"), sellers
    )
    assert got == sellers
