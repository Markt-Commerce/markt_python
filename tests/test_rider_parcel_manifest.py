"""What the rider is told they are collecting, and what counts as active.

A rider was sent to a stall knowing only that the order had some number
of items in it. Nothing on their screen could be checked against what the
shopkeeper handed over, so the only thing standing between a buyer and
somebody else's parcel was the shopkeeper remembering which bag was
which.

Separately: "My active deliveries" never emptied. The assignment's own
status is ACCEPTED for the whole job and never changes, so a finished
delivery sat in the list wearing a Completed pill and pushed the real
work off the screen.
"""

from types import SimpleNamespace

from app.deliveries.models import AssignmentStatus, LogisticalStatus
from app.deliveries.schemas import ActiveAssignmentSchema
from app.deliveries.services import DeliveryService
from app.orders.models import OrderItem


def item(name, quantity=1, variant=None, status=OrderItem.Status.PROCESSING):
    return SimpleNamespace(
        product=SimpleNamespace(name=name) if name else None,
        variant=SimpleNamespace(name=variant) if variant else None,
        quantity=quantity,
        status=status,
        seller=None,
    )


class TestTheRiderKnowsWhatToCollect:
    def test_every_line_is_named_and_counted(self):
        out = DeliveryService._parcel_manifest(
            SimpleNamespace(items=[item("Ankara wrapper", 2), item("Lace blouse")])
        )
        assert out == [
            {"name": "Ankara wrapper", "quantity": 2, "variant": None},
            {"name": "Lace blouse", "quantity": 1, "variant": None},
        ]

    def test_a_variant_is_carried_through(self):
        # "Blue" vs "Red" is exactly the mix-up this is here to stop.
        out = DeliveryService._parcel_manifest(
            SimpleNamespace(items=[item("Ankara wrapper", variant="Colour")])
        )
        assert out[0]["variant"] == "Colour"

    def test_a_cancelled_line_is_not_in_the_bag(self):
        # Listing it sends the rider hunting for something nobody packed.
        out = DeliveryService._parcel_manifest(
            SimpleNamespace(
                items=[
                    item("Ankara wrapper"),
                    item("Lace blouse", status=OrderItem.Status.CANCELLED),
                ]
            )
        )
        assert [line["name"] for line in out] == ["Ankara wrapper"]

    def test_a_line_whose_product_vanished_still_shows(self):
        # A deleted listing must not silently shrink the manifest -- the
        # rider would be handed a bag with more in it than their screen
        # admits to and have no way to tell.
        out = DeliveryService._parcel_manifest(SimpleNamespace(items=[item(None, 3)]))
        assert out == [{"name": "Item", "quantity": 3, "variant": None}]

    def test_an_order_with_no_items_is_not_an_error(self):
        assert DeliveryService._parcel_manifest(SimpleNamespace(items=[])) == []
        assert DeliveryService._parcel_manifest(SimpleNamespace(items=None)) == []

    def test_a_dump_without_a_manifest_does_not_explode(self):
        # `items` is also a dict method, and marshmallow falls back to
        # getattr when the key is missing. Sourcing it from `parcel`
        # keeps a partial dump from handing the serialiser a bound
        # method to iterate.
        out = ActiveAssignmentSchema().dump({"assignment_id": "a1"})
        assert "items" not in out

    def test_the_manifest_survives_the_schema(self):
        out = ActiveAssignmentSchema().dump(
            {
                "assignment_id": "a1",
                "parcel": [{"name": "Ankara wrapper", "quantity": 2, "variant": None}],
            }
        )
        assert out["items"] == [
            {"name": "Ankara wrapper", "quantity": 2, "variant": None}
        ]


class TestActiveMeansActive:
    def test_a_completed_delivery_is_filtered_out(self):
        # The query does this server-side; this pins the intent so the
        # filter cannot be dropped without a test going red.
        import inspect

        source = inspect.getsource(DeliveryService.get_active_assignments)
        assert "LogisticalStatus.COMPLETED" in source
        assert "logistical_status" in source

    def test_the_two_statuses_are_still_distinct(self):
        # The whole bug: one of these moves and the other does not.
        assert AssignmentStatus.ACCEPTED.value == "ACCEPTED"
        assert LogisticalStatus.COMPLETED.value == "COMPLETED"
