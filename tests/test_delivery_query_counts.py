"""Queries that multiplied with the size of the thing being read.

None of these were wrong, and none of them showed up as a bug -- they
just cost one round trip per row, in code that runs on every dashboard
refresh and every five minutes in a worker. The tests pin the shape
rather than the exact count, because what matters is that the number
does not grow with the number of orders.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.deliveries.runs import DeliveryRunService


def item(item_id, seller=None):
    return SimpleNamespace(
        id=item_id,
        status=SimpleNamespace(),
        seller=seller,
        seller_id=getattr(seller, "id", None),
        product_id=f"PRD_{item_id}",
        quantity=1,
    )


class TestWeightsAreReadInOneQuery:
    def test_one_query_however_many_orders(self):
        session = MagicMock()
        chain = session.query.return_value.outerjoin.return_value
        chain.filter.return_value.group_by.return_value.all.return_value = [
            ("ORD_1", 100.0),
            ("ORD_2", 200.0),
        ]

        DeliveryRunService._order_weights_grams(
            session, [f"ORD_{n}" for n in range(1, 21)]
        )

        # Twenty orders, one round trip. This was a query for the items
        # of each order and then another per item for its product.
        assert session.query.call_count == 1

    def test_orders_with_no_rows_still_get_an_answer(self):
        # The caller compares this against a weight ceiling, so a
        # missing key would be an AttributeError on a live attach pass.
        session = MagicMock()
        chain = session.query.return_value.outerjoin.return_value
        chain.filter.return_value.group_by.return_value.all.return_value = []

        out = DeliveryRunService._order_weights_grams(session, ["ORD_1", "ORD_2"])
        assert out == {"ORD_1": 0.0, "ORD_2": 0.0}


class TestReadinessIsOneQueryPerOrder:
    def test_not_one_per_line(self):
        from app.fulfilment.models import FulfilmentAllocationStatus
        from app.orders.models import OrderItem

        items = [
            SimpleNamespace(id=n, status=OrderItem.Status.PROCESSING)
            for n in range(1, 8)
        ]
        order = SimpleNamespace(items=items)

        session = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            (n, FulfilmentAllocationStatus.ACCEPTED) for n in range(1, 8)
        ]

        assert DeliveryRunService._order_is_ready(session, order) is True
        assert session.query.call_count == 1

    def test_the_latest_allocation_per_item_is_the_one_that_counts(self):
        # Rows come back in ascending id, so a later DECLINED must beat
        # an earlier ACCEPTED -- the per-item query this replaced took
        # the newest by ordering descending and taking the first.
        from app.fulfilment.models import FulfilmentAllocationStatus
        from app.orders.models import OrderItem

        order = SimpleNamespace(
            items=[SimpleNamespace(id=1, status=OrderItem.Status.PROCESSING)]
        )
        session = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            (1, FulfilmentAllocationStatus.ACCEPTED),
            (1, FulfilmentAllocationStatus.DECLINED),
        ]

        assert DeliveryRunService._order_is_ready(session, order) is False


class TestResolvingAMarketCostsNothing:
    def test_it_reads_the_relationship(self):
        seller = SimpleNamespace(id=10, market_id=5)
        order = SimpleNamespace(items=[item(1, seller), item(2, seller)])
        session = MagicMock()

        assert DeliveryRunService._resolve_single_market(session, order) == 5
        # The caller eager loads items.seller, so this is free. It used
        # to be a Seller.get() per line of every candidate order.
        session.query.assert_not_called()
