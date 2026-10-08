"""Distance-scoped product queries with a widening fallback."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from external.database import db
from app.libs.geo import (
    RADIUS_LADDER_KM,
    bounding_box,
    haversine_km,
    is_valid_coordinate,
)
from app.libs.session import read_scope

logger = logging.getLogger(__name__)


class LocationScope:
    """Which rung of the ladder produced a result set.

    Reported to the client so the UI can be honest -- "nothing within 10 km,
    showing results from across Oyo" -- instead of silently presenting a shop
    200 km away as if it were nearby.
    """

    NEARBY = "nearby"
    WIDENED = "widened"
    REGIONAL = "regional"
    NATIONWIDE = "nationwide"


def scoped_products(
    lat: Optional[float],
    lng: Optional[float],
    *,
    limit: int = 20,
    cursor: Optional[int] = None,
) -> Dict[str, Any]:
    """Products ranked by distance from a browse location.

    Walks the ladder until something is found, so a thin or brand-new area
    never renders an empty feed:

        <= 10 km  ->  <= 50 km  ->  <= 200 km  ->  nationwide

    No PostGIS: a bounding box does the index-only prefilter and Haversine
    ranks the survivors. If production has the extension, only the two lines
    marked below change -- the ladder, the shape and the caller stay as they
    are.
    """
    from app.products.models import Product
    from app.users.models import Seller

    if not is_valid_coordinate(lat, lng):
        # No usable location: nationwide is the honest answer, not an error.
        return _nationwide(limit, cursor, reason="no-location")

    for radius, scope in zip(
        RADIUS_LADDER_KM,
        (LocationScope.NEARBY, LocationScope.WIDENED, LocationScope.REGIONAL),
    ):
        rows = _within_radius(Product, Seller, lat, lng, radius, limit, cursor)
        if rows:
            return _payload(rows, scope, radius, limit)

    return _nationwide(limit, cursor, reason="nothing-nearby")


def _within_radius(Product, Seller, lat, lng, radius_km, limit, cursor):
    lat_min, lat_max, lng_min, lng_max = bounding_box(lat, lng, radius_km)

    with read_scope() as session:
        q = (
            session.query(Product, Seller.shop_latitude, Seller.shop_longitude).join(
                Seller, Seller.id == Product.seller_id
            )
            # --- the PostGIS swap point -------------------------------------
            # ST_DWithin(seller.geog, ST_MakePoint(:lng,:lat)::geography, :m)
            # replaces these four comparisons and the Haversine pass below.
            .filter(
                Seller.shop_latitude.between(lat_min, lat_max),
                Seller.shop_longitude.between(lng_min, lng_max),
            )
        )
        if cursor:
            q = q.filter(Product.id > cursor)

        # Over-fetch: the box includes corners beyond the radius, and Haversine
        # discards them. Without headroom a full page in could come back short.
        candidates = q.limit(limit * 4).all()

    out = []
    for product, s_lat, s_lng in candidates:
        d = haversine_km(lat, lng, s_lat, s_lng)
        if d <= radius_km:
            out.append((product, d))

    out.sort(key=lambda pair: pair[1])
    return out[:limit]


def _nationwide(limit, cursor, *, reason: str):
    from app.products.models import Product

    with read_scope() as session:
        q = session.query(Product).order_by(Product.created_at.desc())
        if cursor:
            q = q.filter(Product.id > cursor)
        rows = [(p, None) for p in q.limit(limit).all()]

    logger.info("feed fell through to nationwide (%s)", reason)
    return _payload(rows, LocationScope.NATIONWIDE, None, limit)


def _payload(rows: List[tuple], scope: str, radius_km, limit: int) -> Dict[str, Any]:
    return {
        "items": [p for p, _ in rows],
        "distances_km": {
            p.id: (round(d, 1) if d is not None else None) for p, d in rows
        },
        "scope": scope,
        "radius_km": radius_km,
        # Keyset, not OFFSET: distance ranking with OFFSET duplicates and drops
        # rows whenever anything shifts underneath, and the browse location
        # changing mid-scroll is normal here rather than an edge case.
        "next_cursor": rows[-1][0].id if len(rows) == limit else None,
    }
