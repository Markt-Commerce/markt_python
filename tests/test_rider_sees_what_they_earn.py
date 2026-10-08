"""The number a rider decides on has to be the number they get paid.

When riders took the buyer's whole shipping fee, "what the buyer pays" and
"what the rider earns" were the same figure, so the dashboard could show
either. They are different numbers now, and showing the buyer's one to a
rider promises more than the wallet will credit.
"""

from decimal import Decimal

import pytest

from app.deliveries.rider_pay import earning_for_drop
from app.deliveries.run_assignment import _run_total
from app.deliveries.runs import run_base_price
from app.deliveries.schemas import AvailableRunSchema


class FakeRun:
    def __init__(self, base_price, stops):
        self.base_price = base_price
        self.run_orders = [object()] * stops
        self.price_per_order = (
            None if base_price is None else float(base_price) / max(stops, 1)
        )


class TestTheRunFigures:
    def test_a_run_pays_the_rider_less_per_drop_than_each_buyer_pays(self):
        # price_per_order is the buyers' split. Showing it to a rider as
        # their earning overstates it by the platform's share.
        stops = 4
        run = FakeRun(run_base_price(stops), stops)
        per_drop = earning_for_drop(run.base_price, stops=stops)
        assert per_drop < Decimal(str(run.price_per_order))

    def test_the_total_is_the_per_drop_figure_times_the_stops(self):
        stops = 4
        run = FakeRun(run_base_price(stops), stops)
        assert (
            _run_total(run, stops)
            == earning_for_drop(run.base_price, stops=stops) * stops
        )

    def test_a_longer_run_shows_a_bigger_total(self):
        totals = [_run_total(FakeRun(run_base_price(n), n), n) for n in range(1, 6)]
        assert totals == sorted(totals)

    @pytest.mark.parametrize("stops", [0, 1, 4])
    def test_an_unpriced_run_reports_nothing_rather_than_zero(self, stops):
        # A run that has not been priced yet should not advertise ₦0.
        assert _run_total(FakeRun(None, stops), stops) is None

    def test_no_stops_reports_nothing(self):
        assert _run_total(FakeRun(1000, 0), 0) is None


class TestTheSchemaActuallySendsThem:
    def test_the_rider_fields_survive_serialisation(self):
        # Marshmallow drops anything not declared, silently -- the field
        # would simply not be in the response and the app would fall back to
        # showing the buyer's figure again.
        payload = AvailableRunSchema().dump(
            {
                "run_id": "RUN_1",
                "market": "Main",
                "area": "Campus A",
                "order_count": 4,
                "price_per_order": 312.5,
                "rider_earning_per_drop": 250.0,
                "rider_earning_total": 1000.0,
                "distance_meters": 900.0,
                "lat": 6.45,
                "lng": 3.39,
            }
        )
        assert payload["rider_earning_per_drop"] == 250.0
        assert payload["rider_earning_total"] == 1000.0

    def test_an_unpriced_run_serialises_as_null_not_missing(self):
        payload = AvailableRunSchema().dump(
            {
                "run_id": "RUN_1",
                "market": None,
                "area": "Campus A",
                "order_count": 0,
                "price_per_order": None,
                "rider_earning_per_drop": None,
                "rider_earning_total": None,
                "distance_meters": 0.0,
                "lat": None,
                "lng": None,
            }
        )
        assert payload["rider_earning_total"] is None


class TestSingleOrders:
    def test_the_estimate_is_the_share_not_the_shipping_fee(self):
        shipping_fee = 1000
        assert earning_for_drop(shipping_fee, stops=1) < shipping_fee

    def test_an_order_with_no_shipping_fee_estimates_nothing(self):
        assert earning_for_drop(None, stops=1) is None
