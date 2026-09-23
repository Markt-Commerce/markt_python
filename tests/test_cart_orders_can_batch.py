"""Cart orders could never join a delivery run.

DeliveryRunService._order_is_ready calls an order "fully routed and
confirmed" when every item holds a FulfilmentAllocation in ACCEPTED or
PREPARING -- the seller's own "yes, I will fulfil this". The
payment-first checkout opens that window on payment
(complete_checkout_payment). The cart checkout never did.

So every order placed through the app's own basket was paid,
deliverable as a single order, and permanently ineligible for the
batched runs the whole 10.x design is built around -- with no error
anywhere, because the attach pass simply counted it as not yet ready.

Relaxing the run's check was the other way to fix this and the wrong
one: READY_FOR_DELIVERY only means the money arrived.
"""

from unittest.mock import patch

import pytest

from app.libs.errors import ConflictError
from app.payments.services import PaymentService


SPECS = [(1, 7, 2, "PRD_a"), (2, 8, 1, "PRD_b")]


class TestTheSellerWindowOpens:
    def test_every_item_gets_one(self):
        with patch(
            "app.fulfilment.services.FulfilmentService.create_allocation"
        ) as create:
            PaymentService._open_seller_windows(SPECS)

        assert create.call_count == 2
        assert create.call_args_list[0].args == (1, 7, 2)
        assert create.call_args_list[0].kwargs == {"product_id": "PRD_a"}

    def test_nothing_to_do_is_not_an_error(self):
        with patch(
            "app.fulfilment.services.FulfilmentService.create_allocation"
        ) as create:
            PaymentService._open_seller_windows([])
        create.assert_not_called()


class TestARetriedWebhookIsNormalTraffic:
    def test_an_already_open_window_is_success(self):
        # Paystack retries anything that is not a 2xx and re-sends on its
        # own besides. Arriving at an item whose window is already open
        # must not raise.
        with patch(
            "app.fulfilment.services.FulfilmentService.create_allocation",
            side_effect=ConflictError("already allocated"),
        ):
            PaymentService._open_seller_windows(SPECS)

    def test_one_bad_item_does_not_stop_the_others(self):
        calls = []

        def flaky(order_item_id, *args, **kwargs):
            calls.append(order_item_id)
            if order_item_id == 1:
                raise RuntimeError("seller notification exploded")

        with patch(
            "app.fulfilment.services.FulfilmentService.create_allocation",
            side_effect=flaky,
        ):
            PaymentService._open_seller_windows(SPECS)

        # The money is in and the order exists either way.
        assert calls == [1, 2]


class TestTheRunGateStillMeansSomething:
    def test_readiness_is_about_allocations_not_payment(self):
        # Pins why this was fixed at the checkout end rather than by
        # loosening the run's check: an order can be paid and still be
        # one no seller has agreed to fulfil.
        import inspect

        from app.deliveries.runs import DeliveryRunService

        source = inspect.getsource(DeliveryRunService._order_is_ready)
        assert "FulfilmentAllocation" in source
        assert "READY_ALLOCATION_STATUSES" in source


class TestAJobHistoryExists:
    """There was no way for a rider to see their own past work.

    /assignments/active is the only assignment endpoint and it shows
    what they are carrying right now -- so "what did I deliver on
    Tuesday", or checking a payout that looks short, had the earnings
    ledger and nothing to tie its rows back to.
    """

    def test_the_route_is_registered(self):
        from main.setup import create_flask_app

        app = create_flask_app()
        rules = {str(rule) for rule in app.url_map.iter_rules()}
        assert "/api/v1/deliveries/assignments/history" in rules

    def test_only_the_two_filters_a_rider_actually_draws(self):
        from app.deliveries.schemas import DeliveryJobHistoryQuerySchema

        field = DeliveryJobHistoryQuerySchema().fields["status"]
        choices = set(field.validate.choices)
        assert choices == {"active", "completed"}

    def test_no_filter_means_everything(self):
        from app.deliveries.schemas import DeliveryJobHistoryQuerySchema

        # A rider opening the screen should see their whole history,
        # not an arbitrary default slice of it.
        assert DeliveryJobHistoryQuerySchema().load({}) == {"page": 1, "per_page": 20}

    def test_a_job_carries_what_it_paid(self):
        # The wallet says a number arrived; this is what ties it to the
        # job that earned it, which is the whole reason the screen
        # exists.
        from app.deliveries.schemas import DeliveryJobSchema

        assert "earnings" in DeliveryJobSchema().fields
        assert "order_number" in DeliveryJobSchema().fields

    def test_pagination_does_not_collide_with_another_blueprint(self):
        # Nested schemas resolve by name through a global registry, and
        # more than one blueprint defines "PaginationSchema" -- naming
        # this one the same made every request through it a 500.
        from app.deliveries.schemas import DeliveryJobHistoryResponseSchema

        DeliveryJobHistoryResponseSchema().dump(
            {"jobs": [], "pagination": {"page": 1, "per_page": 20}}
        )
