"""What a rider is told about a single-order delivery.

A run's stops have carried a shop name, an address and a phone number
since runs existed. A single order carried two coordinates, so the app had
nothing to print but "Pickup from seller" and no way to call anyone.
"""

from types import SimpleNamespace

import pytest

from app.deliveries.offers import MAX_CONCURRENT_ORDERS
from app.deliveries.schemas import ActiveAssignmentSchema
from app.deliveries.services import DeliveryService


def order(**overrides):
    seller = SimpleNamespace(
        shop_name="Rice Shop",
        shop_address={"street_address": "Stall 4", "city": "Ibadan"},
        shop_latitude=7.37,
        shop_longitude=3.94,
        user=SimpleNamespace(phone_number="2348010000001", address=None),
    )
    data = {
        "items": [SimpleNamespace(seller=seller)],
        "buyer": SimpleNamespace(
            user=SimpleNamespace(username="Tunde", phone_number="2348020000002")
        ),
        "shipping_address": SimpleNamespace(
            street_address="12 Awolowo Rd", city="Ibadan", latitude=7.4, longitude=3.9
        ),
        "order_number": "MK-1",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class TestTheRiderIsToldWhoAndWhere:
    def test_the_shop_is_named(self):
        out = DeliveryService._assignment_parties(order())
        assert out["seller_name"] == "Rice Shop"
        assert "Stall 4" in out["pickup_address"]

    def test_the_buyer_is_named(self):
        out = DeliveryService._assignment_parties(order())
        assert out["buyer_name"] == "Tunde"
        assert "12 Awolowo Rd" in out["dropoff_address"]

    def test_both_ends_can_be_called(self):
        # A rider outside a shut shop, or at a gate with no answer, has no
        # other move.
        out = DeliveryService._assignment_parties(order())
        assert out["seller_phone"] == "2348010000001"
        assert out["buyer_phone"] == "2348020000002"

    def test_a_missing_seller_does_not_raise(self):
        out = DeliveryService._assignment_parties(
            order(items=[SimpleNamespace(seller=None)])
        )
        assert out["seller_name"] is None
        assert out["seller_phone"] is None

    def test_a_missing_address_does_not_print_the_word_none(self):
        out = DeliveryService._assignment_parties(order(shipping_address=None))
        assert out["dropoff_address"] is None


class TestPickupCoordinates:
    def test_the_shop_coordinates_win(self):
        # Resolved from seller.user.address alone before, which is
        # frequently unset -- so the list came back empty and the map had
        # no pickup pin. Same bug as get_available_orders had.
        pickups = DeliveryService.get_assignment_pickups_from_order_item(order())
        assert pickups == [{"lat": 7.37, "lng": 3.94}]

    def test_it_falls_back_to_the_sellers_own_address(self):
        seller = SimpleNamespace(
            shop_name="X",
            shop_address=None,
            shop_latitude=None,
            shop_longitude=None,
            user=SimpleNamespace(
                phone_number=None,
                address=SimpleNamespace(latitude=6.5, longitude=3.3),
            ),
        )
        pickups = DeliveryService.get_assignment_pickups_from_order_item(
            order(items=[SimpleNamespace(seller=seller)])
        )
        assert pickups == [{"lat": 6.5, "lng": 3.3}]

    def test_a_seller_with_no_coordinates_anywhere_is_skipped_not_crashed(self):
        seller = SimpleNamespace(
            shop_name="X",
            shop_address=None,
            shop_latitude=None,
            shop_longitude=None,
            user=SimpleNamespace(phone_number=None, address=None),
        )
        assert (
            DeliveryService.get_assignment_pickups_from_order_item(
                order(items=[SimpleNamespace(seller=seller)])
            )
            == []
        )


class TestTheSchemaSendsThem:
    def test_the_new_fields_survive_serialisation(self):
        # Marshmallow drops anything undeclared without a word.
        payload = ActiveAssignmentSchema().dump(
            {
                "assignment_id": "ASG_1",
                "order_id": "ORD_1",
                "order_number": "MK-1",
                "status": "ACCEPTED",
                "seller_name": "Rice Shop",
                "pickup_address": "Stall 4",
                "seller_phone": "234801",
                "buyer_name": "Tunde",
                "dropoff_address": "12 Awolowo Rd",
                "buyer_phone": "234802",
            }
        )
        assert payload["seller_name"] == "Rice Shop"
        assert payload["buyer_phone"] == "234802"
        assert payload["order_number"] == "MK-1"


class TestHowManyAtOnce:
    def test_there_is_a_limit(self):
        # None at all before: a rider could take every order on the
        # dashboard and leave most of those buyers watching an order that
        # was "on its way" and going cold.
        assert MAX_CONCURRENT_ORDERS >= 1

    def test_it_is_small(self):
        # A rider holding five orders is not five times faster. Batching is
        # the platform's job -- that is what delivery runs are for.
        assert MAX_CONCURRENT_ORDERS <= 3
