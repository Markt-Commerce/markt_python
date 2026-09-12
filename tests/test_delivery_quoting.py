"""The fee engine and quote lifecycle.

The engine is pure arithmetic and is tested directly. Serviceability and
consumption need a real database: the interesting parts are a row lock and an
expiry check that has to happen *inside* it, and a mocked session proves
neither.
"""

import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.delivery_pricing.fees import (
    DEFAULT_FEE_CONFIG,
    FeeBreakdown,
    QuoteContext,
    ZoneBandStrategy,
    get_strategy,
    register_strategy,
)


# ---------------------------------------------------------------------------
# Fee engine
# ---------------------------------------------------------------------------


def _quote(distance_km=1.0, weight=0, base=None):
    return ZoneBandStrategy().quote(
        QuoteContext(
            distance_km=distance_km,
            pickup_zone_id=1,
            dropoff_zone_id=2,
            lane_base_fee_minor=base,
            total_weight_grams=weight,
        )
    )


def test_a_short_hop_is_just_the_base_fee():
    b = _quote(distance_km=1.2)
    assert b.total_minor == DEFAULT_FEE_CONFIG["lane_base_minor"]
    assert [line.label for line in b.lines] == ["Base delivery fee"]


def test_distance_bands_apply_at_their_boundaries():
    """Bands are half-open [lo, hi): 3.0 km is in the second band, not the
    first. An off-by-one here is a fee that changes by ₦200 depending on
    floating-point noise in the last metre."""
    assert _quote(2.999).total_minor == 50_000
    assert _quote(3.0).total_minor == 70_000
    assert _quote(6.999).total_minor == 70_000
    assert _quote(7.0).total_minor == 100_000


def test_beyond_the_last_band_still_prices():
    """Serviceability decides whether a distance is deliverable. The engine
    always returns a number -- returning None here would make "too far" look
    like "pricing failed"."""
    assert (
        _quote(500.0).total_minor == 50_000 + DEFAULT_FEE_CONFIG["beyond_bands_minor"]
    )


def test_a_lane_override_replaces_the_base_not_the_bands():
    b = _quote(distance_km=4.0, base=80_000)
    assert b.total_minor == 80_000 + 20_000


def test_weight_is_charged_per_whole_kilo_over_the_threshold():
    """Rounded up: a 100g overage costs a kilo. That is how couriers price,
    and it stops the fee moving by single kobo."""
    assert _quote(1.0, weight=10_000).total_minor == 50_000  # at threshold, free
    assert _quote(1.0, weight=10_100).total_minor == 55_000  # 1 kg
    assert _quote(1.0, weight=12_000).total_minor == 60_000  # 2 kg


def test_every_amount_is_a_whole_number_of_kobo():
    """No floats anywhere in the total. Money that can carry a fraction of a
    kobo cannot be split evenly across a batch and audited afterwards."""
    for d in (0.5, 3.3, 7.7, 99.9):
        for w in (0, 999, 10_001, 45_500):
            b = _quote(d, w)
            assert isinstance(b.total_minor, int)
            assert all(isinstance(line.amount_minor, int) for line in b.lines)


def test_the_breakdown_sums_to_the_total():
    """The breakdown is shown to the buyer. If it does not add up, they are
    reading a different number from the one they are charged."""
    for d in (1.0, 4.0, 9.0, 40.0):
        b = _quote(d, weight=15_000)
        assert sum(line.amount_minor for line in b.lines) == b.total_minor


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------


def test_the_active_strategy_is_returned_by_default():
    s = get_strategy()
    assert s.name == "zone_band"
    assert s.version


def test_an_unknown_strategy_falls_back_rather_than_raising():
    """A quote replayed against a strategy that has since been removed must
    still produce a number. Raising here would make an old order unreadable."""
    s = get_strategy("strategy_that_was_deleted")
    assert s.name == "zone_band"


def test_a_new_strategy_can_be_registered_without_touching_callers():
    """The whole point of the interface: real landmark data arrives as a new
    implementation, not as an edit to the caller."""

    class LandmarkStub:
        name = "landmark_stub"
        version = "0.0.1"

        def quote(self, ctx):
            return FeeBreakdown(total_minor=12_345, lines=[])

    register_strategy(LandmarkStub)
    assert (
        get_strategy("landmark_stub").quote(QuoteContext(1.0, 1, 2)).total_minor
        == 12_345
    )
