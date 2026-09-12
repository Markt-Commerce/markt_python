"""Splitting a shared delivery run's cost.

Pure arithmetic, but it is arithmetic about money that several people are
each owed a share of, so the properties matter more than the examples: nobody
pays more than going alone, Markt never collects more than the run cost, and
no kobo goes missing.
"""

from datetime import datetime, timedelta

import pytest

from app.delivery_pricing.batch import Participant, Settlement, split


def _p(order_id, solo, minutes=0):
    return Participant(
        order_id=order_id,
        solo_fee_minor=solo,
        joined_at=datetime(2026, 9, 12, 9, 0) + timedelta(minutes=minutes),
    )


# --- the promise the feature is sold on ------------------------------------


def test_sharing_never_costs_more_than_going_alone():
    # A thin run: two buyers, and the run costs more than either was quoted
    # solo. Neither may be charged above their own ceiling.
    s = split([_p("A", 50_000, 0), _p("B", 60_000, 1)], run_cost_minor=200_000)
    assert [x.charged_minor for x in s.shares] == [50_000, 60_000]
    assert all(x.capped for x in s.shares)


def test_a_full_run_is_cheaper_for_everyone():
    # Four buyers sharing a 200_000 run: 50_000 each, under every ceiling.
    people = [
        _p("A", 70_000, 0),
        _p("B", 70_000, 1),
        _p("C", 80_000, 2),
        _p("D", 90_000, 3),
    ]
    s = split(people, run_cost_minor=200_000)
    assert [x.charged_minor for x in s.shares] == [50_000] * 4
    assert not any(x.capped for x in s.shares)
    assert all(x.saved_minor > 0 for x in s.shares)


def test_nobody_ever_pays_above_their_own_quote():
    # Property, over a spread of run costs and ceilings.
    people = [_p("A", 10_000, 0), _p("B", 50_000, 1), _p("C", 99_999, 2)]
    for cost in (0, 1, 7, 30_000, 150_000, 1_000_000):
        s = split(people, run_cost_minor=cost)
        for share in s.shares:
            assert share.charged_minor <= share.solo_fee_minor, (cost, share)


# --- Markt's side ----------------------------------------------------------


def test_a_batch_is_never_a_margin():
    """We never collect more than the run cost. A batch is a saving passed
    on, not a way to make money on delivery."""
    people = [_p("A", 90_000, 0), _p("B", 90_000, 1), _p("C", 90_000, 2)]
    for cost in (0, 1, 999, 100_000, 270_000):
        s = split(people, run_cost_minor=cost)
        assert s.collected_minor <= cost, cost


def test_what_capping_costs_markt_is_visible():
    s = split([_p("A", 20_000, 0), _p("B", 20_000, 1)], run_cost_minor=100_000)
    assert s.collected_minor == 40_000
    assert s.absorbed_minor == 60_000  # not hidden in a rounding difference


def test_a_full_run_absorbs_nothing():
    s = split([_p("A", 70_000, 0), _p("B", 70_000, 1)], run_cost_minor=100_000)
    assert s.absorbed_minor == 0


# --- not one kobo missing ---------------------------------------------------


def test_an_indivisible_cost_still_adds_up_exactly():
    # 100_001 across 3 people does not divide. The total must survive anyway.
    people = [_p("A", 90_000, 0), _p("B", 90_000, 1), _p("C", 90_000, 2)]
    s = split(people, run_cost_minor=100_001)
    assert sum(x.charged_minor for x in s.shares) == 100_001


def test_the_odd_kobo_goes_to_whoever_joined_first():
    people = [_p("C", 90_000, 10), _p("A", 90_000, 0), _p("B", 90_000, 5)]
    # 100_001 over three is 33_333 each with 2 kobo left over, so the two
    # earliest joiners carry one each -- not "the first one carries both".
    s = split(people, run_cost_minor=100_001)
    charged = {x.order_id: x.charged_minor for x in s.shares}
    assert charged["A"] == 33_334  # joined at 0
    assert charged["B"] == 33_334  # joined at 5
    assert charged["C"] == 33_333  # joined at 10
    assert sum(charged.values()) == 100_001
    # The order the list arrived in must not decide who pays more.
    assert charged["C"] < charged["A"]


def test_every_remainder_size_is_conserved():
    people = [_p(str(i), 10_000_000, i) for i in range(7)]
    for cost in range(0, 60):
        s = split(people, run_cost_minor=cost)
        assert sum(x.charged_minor for x in s.shares) == cost, cost


def test_a_participant_with_no_join_time_does_not_win_the_tiebreak():
    """An unknown join time must not be treated as the earliest."""
    known = _p("KNOWN", 90_000, 5)
    unknown = Participant(order_id="UNKNOWN", solo_fee_minor=90_000, joined_at=None)
    s = split([unknown, known], run_cost_minor=1)
    charged = {x.order_id: x.charged_minor for x in s.shares}
    assert charged["KNOWN"] == 1
    assert charged["UNKNOWN"] == 0


# --- edges ------------------------------------------------------------------


def test_a_run_with_nobody_in_it():
    s = split([], run_cost_minor=100_000)
    assert s.shares == ()
    assert s.collected_minor == 0


def test_a_run_of_one_is_just_a_solo_delivery():
    s = split([_p("A", 50_000, 0)], run_cost_minor=80_000)
    assert s.shares[0].charged_minor == 50_000  # their own ceiling, not 80_000


def test_a_free_run_charges_nobody():
    s = split([_p("A", 50_000, 0), _p("B", 50_000, 1)], run_cost_minor=0)
    assert [x.charged_minor for x in s.shares] == [0, 0]


def test_a_negative_run_cost_is_refused():
    # Not a saving: a bug upstream. Better to raise than to quietly pay people.
    with pytest.raises(ValueError):
        split([_p("A", 50_000, 0)], run_cost_minor=-1)


def test_a_buyer_quoted_nothing_pays_nothing():
    s = split([_p("FREE", 0, 0), _p("B", 90_000, 1)], run_cost_minor=100_000)
    charged = {x.order_id: x.charged_minor for x in s.shares}
    assert charged["FREE"] == 0


# --- the flag ---------------------------------------------------------------


def test_batching_is_off_unless_the_environment_says_otherwise(monkeypatch):
    """The money model is only half the feature -- the buyer has to be told
    what happens to their money before agreeing to it."""
    import importlib

    monkeypatch.delenv("DELIVERY_BATCH_ENABLED", raising=False)
    from app.delivery_pricing import batch as batch_module

    importlib.reload(batch_module)
    assert batch_module.batch_enabled() is False
