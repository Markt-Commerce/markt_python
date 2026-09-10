"""Distance maths and bounding boxes, with no database extension required.

PostGIS is not installed on the instance this was written against
(`pg_available_extensions` has no `postgis`), so proximity is done in two
stages, which is standard and fast well past Markt's current scale:

1. a **bounding-box prefilter** on a plain B-tree index over
   ``(latitude, longitude)`` -- cheap, index-only, discards most rows;
2. **Haversine ranking** on what survives -- arithmetic over a small set.

Everything here is pure functions so it can be unit-tested without a database,
and so the single call site in the query layer can be swapped for
``ST_DWithin`` if production turns out to have PostGIS, without any caller
changing.
"""

from __future__ import annotations

import math
from typing import Tuple

EARTH_RADIUS_KM = 6371.0088

# Latitude degrees are effectively constant; longitude degrees shrink towards
# the poles, which is why the box is not square in degrees.
KM_PER_DEGREE_LAT = 110.574


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bounding_box(
    lat: float, lng: float, radius_km: float
) -> Tuple[float, float, float, float]:
    """(lat_min, lat_max, lng_min, lng_max) enclosing the radius.

    Always a superset of the true circle -- the box's corners reach further
    than the radius -- so it is a *prefilter*: the Haversine pass is still
    required to reject the corners. Filtering on the box alone would return
    results up to ~41% beyond the stated radius.
    """
    d_lat = radius_km / KM_PER_DEGREE_LAT

    # cos() collapses at the poles; clamped so a longitude span can never be
    # divided by ~0. Irrelevant for Nigeria, but this is a library function.
    cos_lat = max(math.cos(math.radians(lat)), 0.01)
    d_lng = radius_km / (KM_PER_DEGREE_LAT * cos_lat)

    return (
        max(lat - d_lat, -90.0),
        min(lat + d_lat, 90.0),
        lng - d_lng,
        lng + d_lng,
    )


def is_valid_coordinate(lat, lng) -> bool:
    """Whether a pair is usable as a point at all.

    (0, 0) is deliberately rejected: it is a real place in the Gulf of Guinea,
    but in practice it is what an unset or failed geocode looks like, and
    ~700km off the Nigerian coast is never a shop. Treating it as missing beats
    ranking every such row as equidistant from Lagos.
    """
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return False
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return False
    return not (abs(lat) < 1e-7 and abs(lng) < 1e-7)


# The fallback ladder. A young marketplace in a thin area must never show an
# empty feed because of geography, so the radius widens rather than returning
# nothing. The response reports which rung it used so the UI can say so.
#
# Three radii rather than "10km, 50km, same state": Seller has no state column
# -- the state lives inside a JSON `shop_address` -- so a state rung would mean
# an unindexed JSON filter, or a new column plus a backfill. 200km covers a
# Nigerian state in practice (most are 100-300km across) using the same indexed
# path, which is the better trade until something needs true administrative
# boundaries.
RADIUS_LADDER_KM = (10.0, 50.0, 200.0)
