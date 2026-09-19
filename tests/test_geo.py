"""Proximity maths.

Checked against real Nigerian distances rather than synthetic ones, because a
formula can be self-consistently wrong and only a known-good pair catches it.
"""

import math

import pytest

from app.libs.geo import (
    RADIUS_LADDER_KM,
    bounding_box,
    haversine_km,
    is_valid_coordinate,
)

IKEJA = (6.6018, 3.3515)
LEKKI = (6.4698, 3.5852)
IBADAN = (7.3775, 3.9470)
ABUJA = (9.0765, 7.3986)


def test_known_distances():
    # Straight-line, not by road.
    assert haversine_km(*IKEJA, *LEKKI) == pytest.approx(29.7, abs=1.5)
    assert haversine_km(*IKEJA, *IBADAN) == pytest.approx(108, abs=4)
    assert haversine_km(*IKEJA, *ABUJA) == pytest.approx(524, abs=12)


def test_distance_is_zero_to_itself():
    assert haversine_km(*IKEJA, *IKEJA) == pytest.approx(0, abs=1e-9)


def test_distance_is_symmetric():
    assert haversine_km(*IKEJA, *IBADAN) == pytest.approx(haversine_km(*IBADAN, *IKEJA))


def test_box_contains_the_radius():
    """The box must be a superset of the circle, or the prefilter drops rows
    that are genuinely inside it."""
    lat, lng = IKEJA
    r = 10.0
    lat_min, lat_max, lng_min, lng_max = bounding_box(lat, lng, r)

    # Sample the circle; every point on it must fall inside the box.
    for deg in range(0, 360, 15):
        rad = math.radians(deg)
        d_lat = (r / 110.574) * math.cos(rad)
        d_lng = (r / (110.574 * math.cos(math.radians(lat)))) * math.sin(rad)
        assert lat_min <= lat + d_lat <= lat_max
        assert lng_min <= lng + d_lng <= lng_max


def test_box_is_a_prefilter_not_an_answer():
    """A corner of the box is ~41% further than the radius, which is why the
    Haversine pass still has to run. If this ever became an equality the box
    could be used alone -- it cannot."""
    lat, lng = IKEJA
    lat_min, lat_max, lng_min, lng_max = bounding_box(lat, lng, 10.0)
    corner = haversine_km(lat, lng, lat_max, lng_max)
    assert corner > 10.0


def test_zero_zero_is_not_a_location():
    """It is a real place in the Gulf of Guinea, and in practice it is what a
    failed geocode looks like."""
    assert is_valid_coordinate(0, 0) is False
    assert is_valid_coordinate(0.0, 0.0) is False


def test_rejects_out_of_range_and_junk():
    assert is_valid_coordinate(91, 0) is False
    assert is_valid_coordinate(0, 181) is False
    assert is_valid_coordinate(None, None) is False
    assert is_valid_coordinate("abc", "def") is False


def test_accepts_real_points():
    for p in (IKEJA, LEKKI, IBADAN, ABUJA):
        assert is_valid_coordinate(*p) is True


def test_ladder_widens():
    assert list(RADIUS_LADDER_KM) == sorted(RADIUS_LADDER_KM)
    assert RADIUS_LADDER_KM[0] == 10.0
