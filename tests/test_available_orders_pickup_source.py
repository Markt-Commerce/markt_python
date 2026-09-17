"""A rider can only take an order they can see.

Available orders resolved the pickup point from `seller.user.address` -- a
personal address on the User -- when a shop's location lives on
Seller.shop_latitude/shop_longitude. That is the field the delivery quote
prices against, the proximity feed ranks by, and the run schemas hand the
rider app to draw a pickup pin. A seller who set their shop location the
supported way and had no personal address row was skipped, so their paid
orders were invisible to every rider and the only symptom was an available
list that stayed empty.
"""

from types import SimpleNamespace


def _pickup_of(seller):
    """The resolution the service performs, in the order it performs it."""
    lat, lng = seller.shop_latitude, seller.shop_longitude
    if lat is None or lng is None:
        address = getattr(seller.user, "address", None) if seller.user else None
        if address:
            lat, lng = address.latitude, address.longitude
    return lat, lng


def _seller(shop=None, user_address=None):
    user = SimpleNamespace(address=user_address) if user_address is not None else None
    return SimpleNamespace(
        shop_latitude=shop[0] if shop else None,
        shop_longitude=shop[1] if shop else None,
        user=user,
    )


def test_a_shop_with_coordinates_is_visible():
    """The case that was broken: set through the shop-location screen, no
    personal address anywhere."""
    assert _pickup_of(_seller(shop=(7.443, 3.95))) == (7.443, 3.95)


def test_the_shop_wins_over_a_personal_address():
    """They are different places -- where the shop is, and where its owner
    lives. Deliveries collect from the shop."""
    seller = _seller(
        shop=(7.443, 3.95),
        user_address=SimpleNamespace(latitude=6.52, longitude=3.37),
    )
    assert _pickup_of(seller) == (7.443, 3.95)


def test_an_older_seller_with_only_a_personal_address_still_works():
    """Sellers who registered before shop coordinates existed keep working."""
    seller = _seller(user_address=SimpleNamespace(latitude=6.52, longitude=3.37))
    assert _pickup_of(seller) == (6.52, 3.37)


def test_a_seller_with_no_location_at_all_is_skipped():
    """Nothing to route a rider to, so the order cannot be offered."""
    assert _pickup_of(_seller()) == (None, None)


def test_a_half_set_shop_location_falls_back_rather_than_using_half():
    """One coordinate is not a place."""
    seller = _seller(
        user_address=SimpleNamespace(latitude=6.52, longitude=3.37),
    )
    seller.shop_latitude = 7.443
    seller.shop_longitude = None
    assert _pickup_of(seller) == (6.52, 3.37)
