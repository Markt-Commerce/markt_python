"""The step a rider is on, and who hears when they reach the next one.

Two separate bugs with one shape: something the server knew and never
said.

`logistical_status` is the field that moves as a delivery progresses --
arrived, picked up, en route -- and it was never in the payload. The app
had only `status`, which is ACCEPTED for the whole job, so after a rider
tapped "Arrived at pickup" the screen came back offering "Arrived at
pickup" again, and tapping it a second time was rejected by
is_valid_status_transition as an error the rider could do nothing about.

The buyer and seller heard none of it either: deliveries/services.py had
no notification call anywhere in it, so an order went silent at "paid"
and stayed silent until it turned up at the door.
"""

from types import SimpleNamespace

import pytest

from app.deliveries.models import LogisticalStatus
from app.deliveries.schemas import ActiveAssignmentSchema, AvailableOrderSchema
from app.deliveries.services import DeliveryService
from app.notifications.models import NotificationType


class TestTheAppCanTellTheStepsApart:
    def test_the_status_that_moves_is_in_the_payload(self):
        # The regression. Without this key the app cannot distinguish
        # "on the way to the shop" from "parcel in hand", because
        # `status` reads ACCEPTED for both.
        out = ActiveAssignmentSchema().dump(
            {
                "assignment_id": "a1",
                "order_id": "ORD_1",
                "status": "ACCEPTED",
                "logistical_status": "ARRIVED_PICKUP",
            }
        )
        assert out["logistical_status"] == "ARRIVED_PICKUP"

    def test_a_delivery_nobody_has_started_says_so(self):
        # None is the real state of a freshly accepted order, and it has
        # to survive the dump -- it is what makes "Arrived at pickup" the
        # correct first action exactly once.
        out = ActiveAssignmentSchema().dump(
            {
                "assignment_id": "a1",
                "order_id": "ORD_1",
                "status": "ACCEPTED",
                "logistical_status": None,
            }
        )
        assert out["logistical_status"] is None

    def test_every_step_the_rider_can_reach_survives_the_schema(self):
        for step in LogisticalStatus:
            out = ActiveAssignmentSchema().dump({"logistical_status": step.value})
            assert out["logistical_status"] == step.value


class TestTheOfferSaysWhatTheJobIs:
    def test_the_shop_is_named_before_the_rider_commits(self):
        # These are the same details the assignment hands over *after*
        # accepting. A rider deciding inside a 30-second hold had an
        # order id and a distance.
        out = AvailableOrderSchema().dump(
            {
                "order_id": "ORD_1",
                "seller_name": "Rice Shop",
                "pickup_address": "Stall 4, Ibadan",
                "seller_image": "https://cdn/shop.jpg",
                "pickup_count": 2,
                "item_count": 3,
                "dropoff_area": "Bodija",
            }
        )
        assert out["seller_name"] == "Rice Shop"
        assert out["pickup_address"] == "Stall 4, Ibadan"
        assert out["seller_image"] == "https://cdn/shop.jpg"
        assert out["pickup_count"] == 2
        assert out["item_count"] == 3
        assert out["dropoff_area"] == "Bodija"


class TestTheShopsPicture:
    def test_the_shop_avatar_wins(self):
        seller = SimpleNamespace(
            user=SimpleNamespace(profile_picture="https://cdn/avatar.jpg"),
            banner_url="https://cdn/banner.jpg",
        )
        assert DeliveryService._shop_image(seller) == "https://cdn/avatar.jpg"

    def test_the_column_default_is_not_a_url(self):
        # "default.jpg" is what the column holds for a seller who never
        # set a picture. Sending it gives the app a broken image, which
        # is worse than sending nothing.
        seller = SimpleNamespace(
            user=SimpleNamespace(profile_picture="default.jpg"),
            banner_url="https://cdn/banner.jpg",
        )
        assert DeliveryService._shop_image(seller) == "https://cdn/banner.jpg"

    def test_no_picture_anywhere_is_none_not_a_filename(self):
        seller = SimpleNamespace(
            user=SimpleNamespace(profile_picture="default.jpg"), banner_url=None
        )
        assert DeliveryService._shop_image(seller) is None

    def test_a_missing_seller_does_not_raise(self):
        assert DeliveryService._shop_image(None) is None


AUDIENCE = {
    "order_id": "ORD_1",
    "order_number": "MK-1",
    "buyer_user_id": "USR_buyer",
    "seller_user_ids": ["USR_seller"],
    "rider_name": "Musa",
}


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake(user_id, notification_type, **kwargs):
        calls.append((user_id, notification_type, kwargs.get("metadata_", {})))

    monkeypatch.setattr(
        "app.deliveries.services.NotificationService.create_notification", fake
    )
    return calls


class TestWhoHearsAboutEachStep:
    def test_the_buyer_hears_about_every_step(self, sent):
        for step in (
            LogisticalStatus.ARRIVED_PICKUP,
            LogisticalStatus.PICKED_UP,
            LogisticalStatus.EN_ROUTE_TO_DROPOFF,
            LogisticalStatus.DELIVERED_PENDING_QR,
        ):
            sent.clear()
            DeliveryService._notify_delivery_progress(AUDIENCE, step)
            buyers = [c for c in sent if c[0] == "USR_buyer"]
            assert len(buyers) == 1, f"buyer heard nothing about {step.value}"
            assert buyers[0][1] == NotificationType.DELIVERY_STATUS_UPDATE

    def test_the_seller_hears_only_what_concerns_their_shop(self, sent):
        # Someone is coming, and someone is outside. A seller does not
        # need to know the rider has set off for a buyer across town.
        DeliveryService._notify_delivery_progress(
            AUDIENCE, LogisticalStatus.EN_ROUTE_TO_DROPOFF
        )
        assert [c for c in sent if c[0] == "USR_seller"] == []

        sent.clear()
        DeliveryService._notify_delivery_progress(
            AUDIENCE, LogisticalStatus.ARRIVED_PICKUP
        )
        sellers = [c for c in sent if c[0] == "USR_seller"]
        assert len(sellers) == 1
        assert sellers[0][1] == NotificationType.DELIVERY_PICKUP_UPDATE

    def test_delivered_is_not_announced_twice(self, sent):
        # The POD confirm path already tells both sides it arrived.
        DeliveryService._notify_delivery_progress(AUDIENCE, LogisticalStatus.COMPLETED)
        assert sent == []

    def test_the_message_names_the_rider_and_the_order(self, sent):
        DeliveryService._notify_delivery_progress(AUDIENCE, LogisticalStatus.PICKED_UP)
        message = sent[0][2]["message"]
        assert "Musa" in message
        assert "MK-1" in message
        # The push body is what lands on a lock screen -- an unfilled
        # placeholder there is worse than a plainer sentence.
        assert "{" not in message

    def test_an_order_with_no_number_falls_back_to_its_id(self, sent):
        DeliveryService._notify_delivery_progress(
            {**AUDIENCE, "order_number": None}, LogisticalStatus.PICKED_UP
        )
        assert "ORD_1" in sent[0][2]["message"]

    def test_every_shop_in_a_multi_seller_order_is_told(self, sent):
        DeliveryService._notify_delivery_progress(
            {**AUDIENCE, "seller_user_ids": ["USR_a", "USR_b"]},
            LogisticalStatus.ARRIVED_PICKUP,
        )
        assert {c[0] for c in sent} == {"USR_buyer", "USR_a", "USR_b"}

    def test_a_delivery_does_not_fail_because_a_notification_did(self, monkeypatch):
        # The rider has already moved and the step is already committed.
        # Raising here would turn a working delivery into a 500.
        def boom(*args, **kwargs):
            raise RuntimeError("push provider down")

        monkeypatch.setattr(
            "app.deliveries.services.NotificationService.create_notification", boom
        )
        DeliveryService._notify_delivery_progress(AUDIENCE, LogisticalStatus.PICKED_UP)

    def test_an_order_whose_people_could_not_be_resolved_is_skipped(self, sent):
        DeliveryService._notify_delivery_progress({}, LogisticalStatus.PICKED_UP)
        assert sent == []


class TestWorkingOutWhoToTellCannotBreakTheDelivery:
    def test_an_order_that_vanished_tells_nobody_rather_than_raising(self):
        session = SimpleNamespace(
            query=lambda *a, **k: SimpleNamespace(
                filter_by=lambda **kw: SimpleNamespace(first=lambda: None)
            )
        )
        assert (
            DeliveryService._delivery_audience(
                session, SimpleNamespace(order_id="ORD_1", assignment_id="ASG_1")
            )
            == {}
        )

    def test_a_broken_session_does_not_undo_the_step_the_rider_took(self):
        # This runs inside the transaction that just recorded a real
        # movement. Whatever goes wrong deciding who to tell, the rider
        # has already arrived and the commit has to stand.
        class Boom:
            def query(self, *args, **kwargs):
                raise RuntimeError("connection lost")

        assert (
            DeliveryService._delivery_audience(
                Boom(), SimpleNamespace(order_id="ORD_1", assignment_id="ASG_1")
            )
            == {}
        )

    def test_a_rider_with_no_name_is_still_somebody(self):
        order = SimpleNamespace(id="ORD_1", order_number="MK-1", buyer=None, items=[])
        session = SimpleNamespace(
            query=lambda *a, **k: SimpleNamespace(
                filter_by=lambda **kw: SimpleNamespace(first=lambda: order)
            )
        )
        out = DeliveryService._delivery_audience(
            session, SimpleNamespace(order_id="ORD_1", delivery_user=None)
        )
        assert out["rider_name"] == "Your rider"
