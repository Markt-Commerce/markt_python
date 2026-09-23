"""Parcels stranded with a rider who stopped mid-run.

Giving up a run after collecting used to leave nothing behind. The run
was held at RIDER_FAILED, the goods were in somebody's bag, and no
record anywhere said so -- the resolution machinery already existed
(resolve_failure picks an action and who pays, complete_recovery
records it happened) but nothing was creating the failures that feed
it, so a stranded parcel had no representation at all.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.deliveries.failure import record_abandoned_run
from app.deliveries.models import (
    DeliveryFailureOutcome,
    DeliveryFailureReason,
    DeliveryRunStopStatus,
)
from app.orders.models import OrderItem


def stop(seller_id, status):
    return SimpleNamespace(seller_id=seller_id, status=status)


def order(order_id, seller_ids, cancelled=()):
    return SimpleNamespace(
        id=order_id,
        items=[
            SimpleNamespace(
                seller_id=seller_id,
                product_id=f"PRD_{seller_id}",
                status=(
                    OrderItem.Status.CANCELLED
                    if seller_id in cancelled
                    else OrderItem.Status.PROCESSING
                ),
            )
            for seller_id in seller_ids
        ],
    )


def _run(stops, orders, existing_failures=()):
    session = MagicMock()
    added = []
    session.add.side_effect = added.append

    def query(model):
        q = MagicMock()
        name = getattr(model, "__name__", str(model))
        if name == "DeliveryRunStop":
            q.filter_by.return_value.all.return_value = stops
        elif name == "DeliveryRunOrder":
            q.filter_by.return_value.all.return_value = [
                SimpleNamespace(order_id=o.id) for o in orders
            ]
        elif name == "Order":
            q.filter.return_value.all.return_value = orders
        elif name == "DeliveryFailure":
            q.filter.return_value.all.return_value = list(existing_failures)
        else:  # ProductHandling
            q.filter.return_value.first.return_value = None
        return q

    session.query.side_effect = query

    with patch("app.deliveries.failure.OrderEventService.emit"):
        affected = record_abandoned_run(session, "RUN_1", "DEL_1")
    return affected, added


class TestOnlyWhatHasLeftAShop:
    def test_an_order_from_a_collected_shop_is_recorded(self):
        affected, added = _run(
            [stop(7, DeliveryRunStopStatus.PICKED_UP)], [order("ORD_1", [7])]
        )
        assert affected == ["ORD_1"]
        assert added[0].reason is DeliveryFailureReason.RIDER_UNABLE
        assert added[0].outcome is DeliveryFailureOutcome.PENDING
        assert added[0].delivery_run_id == "RUN_1"

    def test_an_order_from_a_shop_never_reached_is_left_alone(self):
        # It rides along when the run is reassigned. Opening a failure
        # would put a decision in front of somebody that does not need
        # making.
        affected, added = _run(
            [
                stop(7, DeliveryRunStopStatus.PICKED_UP),
                stop(8, DeliveryRunStopStatus.PENDING),
            ],
            [order("ORD_1", [7]), order("ORD_2", [8])],
        )
        assert affected == ["ORD_1"]
        assert len(added) == 1

    def test_arriving_is_not_collecting(self):
        # The rider stood outside and left. Nothing is in their bag.
        affected, added = _run(
            [stop(7, DeliveryRunStopStatus.ARRIVED)], [order("ORD_1", [7])]
        )
        assert affected == []
        assert added == []

    def test_nothing_collected_at_all_records_nothing(self):
        affected, added = _run([], [order("ORD_1", [7])])
        assert affected == []
        assert added == []

    def test_a_cancelled_line_does_not_strand_an_order(self):
        # Nobody packed it, so the rider is not carrying it.
        affected, added = _run(
            [stop(7, DeliveryRunStopStatus.PICKED_UP)],
            [order("ORD_1", [7], cancelled={7})],
        )
        assert affected == []

    def test_an_order_spanning_two_shops_counts_if_either_was_collected(self):
        affected, _ = _run(
            [
                stop(7, DeliveryRunStopStatus.PICKED_UP),
                stop(8, DeliveryRunStopStatus.PENDING),
            ],
            [order("ORD_1", [7, 8])],
        )
        assert affected == ["ORD_1"]


class TestItDoesNotDuplicate:
    def test_an_order_already_reported_is_skipped(self):
        # A rider who reported a failed drop and then broke down should
        # not leave two open records for the same parcel.
        affected, added = _run(
            [stop(7, DeliveryRunStopStatus.PICKED_UP)],
            [order("ORD_1", [7]), order("ORD_2", [7])],
            existing_failures=[SimpleNamespace(order_id="ORD_1")],
        )
        assert affected == ["ORD_2"]
        assert len(added) == 1


class TestItEntersTheExistingPipeline:
    def test_the_record_is_pending_a_human_decision(self):
        # resolve_failure chooses redelivery/return/dispose and who
        # pays; complete_recovery records it was carried out. Neither
        # is derived here.
        _, added = _run(
            [stop(7, DeliveryRunStopStatus.PICKED_UP)], [order("ORD_1", [7])]
        )
        assert added[0].outcome is DeliveryFailureOutcome.PENDING
        assert getattr(added[0], "recovery_action", None) is None

    def test_the_reporting_rider_is_on_the_record(self):
        # They are the one holding the goods, so whoever works this
        # needs to know who to call.
        _, added = _run(
            [stop(7, DeliveryRunStopStatus.PICKED_UP)], [order("ORD_1", [7])]
        )
        assert added[0].reported_by_delivery_user_id == "DEL_1"
