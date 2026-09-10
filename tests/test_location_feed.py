"""The browse location and the distance-scoped feed.

The behaviour that matters most here is the fallback ladder: a young
marketplace in a thin area must never render an empty feed because of
geography.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.libs.geo import RADIUS_LADDER_KM
from app.location import services
from app.location.services import LocationScope, scoped_products

IKEJA = (6.6018, 3.3515)


def _product(pid, price=1000.0, seller_id=1):
    p = MagicMock()
    p.id = pid
    p.name = f"Product {pid}"
    p.price = price
    p.seller_id = seller_id
    return p


def _scope_with(rows):
    """A read_scope whose query chain returns `rows`."""
    session = MagicMock()
    chain = session.query.return_value.join.return_value.filter.return_value
    chain.filter.return_value = chain
    chain.limit.return_value.all.return_value = rows
    # nationwide path
    session.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
        r[0] for r in rows
    ]
    scope = MagicMock()
    scope.__enter__ = MagicMock(return_value=session)
    scope.__exit__ = MagicMock(return_value=False)
    return scope


def test_a_shop_in_range_is_scoped_nearby():
    # ~2.9 km from Ikeja.
    rows = [(_product("PRD_1"), 6.6250, 3.3400)]
    with patch.object(services, "read_scope", return_value=_scope_with(rows)):
        result = scoped_products(*IKEJA, limit=5)

    assert result["scope"] == LocationScope.NEARBY
    assert result["radius_km"] == RADIUS_LADDER_KM[0]
    assert result["distances_km"]["PRD_1"] == pytest.approx(2.9, abs=0.4)


def test_a_distant_shop_falls_through_to_nationwide():
    """Abuja is ~520 km from Ikeja — past every rung.

    The point is that it still returns rows. An empty feed is the one outcome
    the ladder exists to prevent.
    """
    rows = [(_product("PRD_FAR"), 9.0765, 7.3986)]
    with patch.object(services, "read_scope", return_value=_scope_with(rows)):
        result = scoped_products(*IKEJA, limit=5)

    assert result["scope"] == LocationScope.NATIONWIDE
    assert len(result["items"]) == 1
    # Honest about it: no distance is claimed for a nationwide row.
    assert result["distances_km"]["PRD_FAR"] is None


def test_no_location_returns_nationwide_rather_than_failing():
    rows = [(_product("PRD_1"), 6.6, 3.3)]
    with patch.object(services, "read_scope", return_value=_scope_with(rows)):
        result = scoped_products(None, None, limit=5)
    assert result["scope"] == LocationScope.NATIONWIDE


def test_zero_zero_is_treated_as_no_location():
    """(0, 0) is what a failed geocode looks like. Ranking every such row as
    equidistant from Lagos would be worse than ignoring it."""
    rows = [(_product("PRD_1"), 6.6, 3.3)]
    with patch.object(services, "read_scope", return_value=_scope_with(rows)):
        result = scoped_products(0, 0, limit=5)
    assert result["scope"] == LocationScope.NATIONWIDE


def test_results_are_ordered_by_distance():
    rows = [
        (_product("FAR"), 6.72, 3.30),  # ~14 km
        (_product("NEAR"), 6.6100, 3.3520),  # ~1 km
        (_product("MID"), 6.6400, 3.3600),  # ~4 km
    ]
    with patch.object(services, "read_scope", return_value=_scope_with(rows)):
        result = scoped_products(*IKEJA, limit=5)

    ids = [p.id for p in result["items"]]
    assert ids[0] == "NEAR", f"nearest must rank first, got {ids}"
    assert ids.index("MID") < ids.index("FAR") if "FAR" in ids else True


def test_the_box_corner_is_rejected_by_the_haversine_pass():
    """A row inside the bounding box but outside the radius must not be
    returned as 'nearby'. If the second pass were ever dropped as an
    optimisation, this is the test that fails."""
    # North-east corner of the 10 km box is ~14 km away.
    rows = [(_product("CORNER"), 6.6922, 3.4425)]
    with patch.object(services, "read_scope", return_value=_scope_with(rows)):
        result = scoped_products(*IKEJA, limit=5)

    assert result["scope"] != LocationScope.NEARBY
