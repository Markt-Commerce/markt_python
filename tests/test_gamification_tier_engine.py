"""Unit tests for the pure tier engine (points -> tier). No DB/Redis needed."""

import pytest

from app.gamification.tier_engine import (
    compute_tier,
    next_tier,
    tier_progress,
    tier_key_for,
)
from app.gamification.constants import TIER_SEED


# --- compute_tier / tier_key_for ------------------------------------------- #
@pytest.mark.parametrize(
    "points,expected",
    [
        (0, "newcomer"),
        (1, "newcomer"),
        (99, "newcomer"),
        (100, "hustler"),
        (499, "hustler"),
        (500, "trader"),
        (1499, "trader"),
        (1500, "merchant"),
        (4999, "merchant"),
        (5000, "magnate"),
        (14999, "magnate"),
        (15000, "mogul"),
        (10**9, "mogul"),
    ],
)
def test_tier_boundaries(points, expected):
    assert tier_key_for(points) == expected
    assert compute_tier(points)["tier"] == expected


def test_negative_points_clamp_to_lowest_tier():
    assert tier_key_for(-50) == "newcomer"


def test_compute_tier_returns_full_row():
    row = compute_tier(1500)
    assert row["name"] == "Merchant"
    assert row["star_count"] == 3
    assert row["min_lifetime_points"] == 1500
    assert row["color_hex"].startswith("#")


# --- next_tier ------------------------------------------------------------- #
def test_next_tier_from_newcomer():
    assert next_tier(0)["tier"] == "hustler"


def test_next_tier_mid_ladder():
    assert next_tier(500)["tier"] == "merchant"


def test_next_tier_at_top_is_none():
    assert next_tier(15000) is None
    assert next_tier(999999) is None


# --- tier_progress --------------------------------------------------------- #
def test_progress_at_tier_floor_is_zero():
    prog = tier_progress(100)  # exactly hustler floor
    assert prog["current"]["tier"] == "hustler"
    assert prog["progress_to_next"] == 0.0
    assert prog["points_to_next_tier"] == 400  # 500 - 100


def test_progress_midway():
    # Hustler floor 100, trader floor 500 -> span 400. At 300 -> 200/400 = 0.5.
    prog = tier_progress(300)
    assert prog["current"]["tier"] == "hustler"
    assert prog["next"]["tier"] == "trader"
    assert prog["progress_to_next"] == pytest.approx(0.5)
    assert prog["points_to_next_tier"] == 200


def test_progress_at_max_tier():
    prog = tier_progress(20000)
    assert prog["current"]["tier"] == "mogul"
    assert prog["next"] is None
    assert prog["progress_to_next"] == 1.0
    assert prog["points_to_next_tier"] == 0


def test_progress_is_bounded_0_1():
    for pts in (0, 50, 100, 1234, 4999, 5000, 100000):
        prog = tier_progress(pts)
        assert 0.0 <= prog["progress_to_next"] <= 1.0


# --- custom tier rows ------------------------------------------------------ #
def test_custom_unsorted_rows_are_sorted():
    rows = [
        {
            "tier": "b",
            "name": "B",
            "star_count": 1,
            "min_lifetime_points": 100,
            "color_hex": "#111111",
        },
        {
            "tier": "a",
            "name": "A",
            "star_count": 0,
            "min_lifetime_points": 0,
            "color_hex": "#000000",
        },
        {
            "tier": "c",
            "name": "C",
            "star_count": 2,
            "min_lifetime_points": 300,
            "color_hex": "#222222",
        },
    ]
    assert tier_key_for(0, rows) == "a"
    assert tier_key_for(150, rows) == "b"
    assert tier_key_for(500, rows) == "c"
    assert next_tier(150, rows)["tier"] == "c"


def test_default_seed_has_six_tiers():
    assert len(TIER_SEED) == 6
    assert {t["tier"] for t in TIER_SEED} == {
        "newcomer",
        "hustler",
        "trader",
        "merchant",
        "magnate",
        "mogul",
    }
