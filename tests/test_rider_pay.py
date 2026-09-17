"""What a rider earns, and why the numbers have to move in these directions.

These are property tests, not value tests. The rates in rider_pay.py and
runs.py are placeholders somebody has to set from real cost data; the
relationships between them are the decision, and those are what break
silently if a rate is changed carelessly.
"""

from decimal import Decimal

import pytest

from app.deliveries.rider_pay import (
    MIN_DROP_EARNING,
    RIDER_REVENUE_SHARE,
    earning_for_drop,
)
from app.deliveries.runs import DEFAULT_BASE_PRICE, run_base_price


def rider_total(stops):
    """What a rider takes home for a whole run of this size."""
    return earning_for_drop(run_base_price(stops), stops) * stops


class TestBatchingPaysMore:
    def test_a_longer_run_pays_the_rider_more(self):
        # The defect this replaces: a run was priced flat, so four drops
        # collected what one drop collected and the rider's total never moved.
        totals = [rider_total(n) for n in range(1, 8)]
        assert totals == sorted(totals)
        assert totals[0] < totals[-1]

    def test_every_extra_stop_adds_pay(self):
        for n in range(1, 8):
            assert rider_total(n + 1) > rider_total(n), f"{n} -> {n+1}"

    def test_the_run_price_itself_rises_with_stops(self):
        prices = [run_base_price(n) for n in range(1, 8)]
        assert prices == sorted(prices)


class TestBatchingIsCheaperPerBuyer:
    def test_each_buyers_share_falls_as_the_run_fills(self):
        shares = [run_base_price(n) / n for n in range(1, 8)]
        assert shares == sorted(shares, reverse=True)

    def test_a_shared_run_always_beats_delivering_alone(self):
        for n in range(2, 8):
            assert run_base_price(n) / n < run_base_price(1)


class TestPerDropFalls:
    def test_a_drop_on_a_full_run_pays_less_than_a_solo_drop(self):
        # This is what makes the buyer's share cheaper. The rider comes out
        # ahead on the trip, not on the individual drop.
        solo = earning_for_drop(run_base_price(1), stops=1)
        assert earning_for_drop(run_base_price(4), stops=4) < solo


class TestNeverPaysOutMoreThanItCollects:
    @pytest.mark.parametrize("stops", [1, 2, 3, 4, 8, 15])
    def test_the_rider_share_is_a_fraction_of_revenue(self, stops):
        revenue = run_base_price(stops)
        assert rider_total(stops) <= Decimal(str(revenue))

    def test_the_share_is_less_than_all_of_it(self):
        assert RIDER_REVENUE_SHARE < 1


class TestSoloDelivery:
    def test_the_rider_no_longer_takes_the_whole_shipping_fee(self):
        # Every naira of the buyer's delivery fee used to go to the rider, so
        # there was nothing left to fund the batched runs riders are meant to
        # prefer.
        assert earning_for_drop(1000, stops=1) < 1000

    def test_a_longer_delivery_pays_more(self):
        # The fee engine charges more for distance; the rider should see it.
        assert earning_for_drop(1500, stops=1) > earning_for_drop(500, stops=1)


class TestFloor:
    def test_a_tiny_trip_still_pays_the_floor(self):
        assert earning_for_drop(10, stops=1) == MIN_DROP_EARNING

    def test_a_heavily_split_run_still_pays_the_floor_per_drop(self):
        assert earning_for_drop(100, stops=20) == MIN_DROP_EARNING


class TestNoRevenueNoPayment:
    @pytest.mark.parametrize("revenue", [None, 0, -50])
    def test_nothing_to_pay_from_credits_nothing(self, revenue):
        # Not the floor: callers treat None as "credit nothing", and a floor
        # paid against revenue that does not exist is money invented.
        assert earning_for_drop(revenue, stops=1) is None


class TestStopsAreSanitised:
    @pytest.mark.parametrize("stops", [0, None, -3])
    def test_a_missing_stop_count_is_treated_as_one(self, stops):
        assert earning_for_drop(500, stops=stops) == earning_for_drop(500, stops=1)


class TestOneStopPricingIsUnchanged:
    def test_a_single_stop_run_costs_what_it_always_did(self):
        # Splitting the flat fee into trip + per-stop deliberately leaves the
        # one-stop price alone, so nothing buyer-facing moves unless a run
        # actually carries more than one drop.
        assert run_base_price(1) == DEFAULT_BASE_PRICE
