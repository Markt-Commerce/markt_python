"""One rider collecting from several nearby shops for one buyer.

Markt baskets routinely span two stalls in the same market. Charging two full
delivery fees for one trip is charging twice for a journey the buyer can see
is single.
"""

import pytest

from app.delivery_pricing.combined import (
    CombinedQuote,
    Pickup,
    allocate,
    can_combine,
    max_pickup_spread_km,
)

# Two real Ogbomoso points ~250m apart, and one 5km away.
NEAR_A = (8.1467, 4.2516)
NEAR_B = (8.1489, 4.2521)
FAR = (8.1673, 4.2670)


def _p(seller_id, coords, solo):
    return Pickup(
        seller_id=seller_id, lat=coords[0], lng=coords[1], solo_fee_minor=solo
    )


# --- whether a trip can be shared at all ------------------------------------


def test_two_shops_next_door_can_share_a_rider():
    assert can_combine([_p(1, NEAR_A, 50_000), _p(2, NEAR_B, 50_000)]) is True


def test_two_shops_across_town_cannot():
    assert can_combine([_p(1, NEAR_A, 50_000), _p(2, FAR, 70_000)]) is False


def test_one_shop_is_not_a_combination():
    assert can_combine([_p(1, NEAR_A, 50_000)]) is False
    assert can_combine([]) is False


def test_every_pair_must_be_close_not_just_consecutive():
    """Three shops in a line, each just inside the limit from the next, are
    twice the limit end to end -- a detour however you order the stops."""
    limit = max_pickup_spread_km()
    step = limit * 0.9 / 111.32  # degrees latitude
    chain = [
        _p(1, (8.1400, 4.2500), 50_000),
        _p(2, (8.1400 + step, 4.2500), 50_000),
        _p(3, (8.1400 + 2 * step, 4.2500), 50_000),
    ]
    assert can_combine(chain) is False


# --- the promise ------------------------------------------------------------


def test_nobody_pays_more_than_going_alone():
    pickups = [_p(1, NEAR_A, 50_000), _p(2, NEAR_B, 70_000)]
    for fee in (0, 1, 50_000, 120_000, 500_000):
        q = allocate(pickups, fee)
        for s in q.shares:
            assert s.charged_minor <= s.solo_fee_minor, (fee, s)


def test_the_near_shop_does_not_subsidise_the_far_one():
    """A batch splits equally because everyone gets the same thing. Here they
    do not: one order's shop may be a kilometre away and another's six."""
    q = allocate([_p(1, NEAR_A, 20_000), _p(2, NEAR_B, 80_000)], 50_000)
    charged = {s.seller_id: s.charged_minor for s in q.shares}
    assert charged[1] < charged[2]
    # 20k:80k is 1:4, so 50k splits 10k/40k.
    assert charged[1] == 10_000
    assert charged[2] == 40_000


def test_not_one_kobo_goes_missing():
    pickups = [_p(1, NEAR_A, 33_333), _p(2, NEAR_B, 33_333), _p(3, NEAR_A, 33_334)]
    for fee in range(0, 60):
        q = allocate(pickups, fee)
        assert sum(s.charged_minor for s in q.shares) == fee, fee


def test_markt_never_collects_more_than_the_trip_costs():
    pickups = [_p(1, NEAR_A, 50_000), _p(2, NEAR_B, 50_000)]
    for fee in (0, 999, 70_000, 100_000):
        q = allocate(pickups, fee)
        assert sum(s.charged_minor for s in q.shares) <= fee


# --- when to offer it -------------------------------------------------------


def test_a_combined_trip_that_saves_nothing_is_not_offered():
    """It ties two orders to one rider's schedule for no gain, which is a
    worse deal than it looks."""
    q = allocate([_p(1, NEAR_A, 50_000), _p(2, NEAR_B, 50_000)], 100_000)
    assert q.saved_minor == 0
    assert q.worth_offering is False


def test_a_real_saving_is_offered_and_reported():
    q = allocate([_p(1, NEAR_A, 50_000), _p(2, NEAR_B, 50_000)], 70_000)
    assert q.separate_fee_minor == 100_000
    assert q.saved_minor == 30_000
    assert q.worth_offering is True


# --- edges ------------------------------------------------------------------


def test_a_free_trip_charges_nobody():
    q = allocate([_p(1, NEAR_A, 50_000), _p(2, NEAR_B, 50_000)], 0)
    assert all(s.charged_minor == 0 for s in q.shares)


def test_every_leg_free_divides_by_nothing():
    q = allocate([_p(1, NEAR_A, 0), _p(2, NEAR_B, 0)], 50_000)
    assert all(s.charged_minor == 0 for s in q.shares)


def test_a_negative_fee_is_refused():
    with pytest.raises(ValueError):
        allocate([_p(1, NEAR_A, 50_000)], -1)


def test_no_pickups_is_refused():
    with pytest.raises(ValueError):
        allocate([], 50_000)


def test_the_split_does_not_depend_on_input_order():
    a = allocate([_p(1, NEAR_A, 20_000), _p(2, NEAR_B, 80_000)], 50_001)
    b = allocate([_p(2, NEAR_B, 80_000), _p(1, NEAR_A, 20_000)], 50_001)
    assert {s.seller_id: s.charged_minor for s in a.shares} == {
        s.seller_id: s.charged_minor for s in b.shares
    }
