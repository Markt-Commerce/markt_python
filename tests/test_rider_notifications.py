"""Riders can be notified at all.

Notification.user_id and PushToken.user_id both referenced `users`, and a
DeliveryUser lives in `delivery_users` with a DEL_ id -- so the row was
refused by the foreign key. Every notification call site wraps itself in
`except Exception`, so nothing ever said so: the rider app had no way to be
told anything, and no way to register for push even once it asked.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.notifications.models import NotificationType
from app.notifications.services import NotificationService, _owner_column


class TestOwnerRouting:
    def test_a_rider_id_routes_to_the_rider_column(self):
        assert NotificationService._owner_filter("DEL_abc") == {
            "delivery_user_id": "DEL_abc"
        }

    def test_a_shopper_id_routes_to_the_user_column(self):
        assert NotificationService._owner_filter("USR_abc") == {"user_id": "USR_abc"}

    def test_reads_follow_the_same_split(self):
        assert _owner_column("DEL_abc") == "delivery_user_id"
        assert _owner_column("USR_abc") == "user_id"

    def test_an_unprefixed_id_is_treated_as_a_shopper(self):
        """The old ids, and anything a caller passes that is not a rider."""
        assert NotificationService._owner_filter("12345") == {"user_id": "12345"}


class TestTheDeliveryPayload:
    """The bug that stopped every push and every notification email.

    deliver_notification reads notification_data["user_id"] first thing, and
    to_dict() did not put it there -- so every queued delivery raised KeyError
    before it started. The websocket path kept working, because it is called
    with the id directly rather than out of this payload.
    """

    def _notification(self, **kwargs):
        from app.notifications.models import Notification

        return Notification(
            type=NotificationType.ORDER_PLACED, title="t", message="m", **kwargs
        )

    def test_a_shoppers_notification_names_them(self):
        assert self._notification(user_id="USR_1").to_dict()["user_id"] == "USR_1"

    def test_a_riders_notification_names_them(self):
        assert (
            self._notification(delivery_user_id="DEL_1").to_dict()["user_id"] == "DEL_1"
        )


class TestTemplates:
    def test_every_rider_type_has_a_template_and_a_channel_policy(self):
        for t in (
            NotificationType.DELIVERY_AVAILABLE,
            NotificationType.DELIVERY_ASSIGNED,
            NotificationType.DELIVERY_EARNING_CREDITED,
        ):
            assert t in NotificationService.TEMPLATES, t
            assert t in NotificationService.CHANNEL_CONFIG, t

    def test_a_new_delivery_pushes_even_when_the_app_is_open(self):
        """A rider who misses this has lost the job to someone else. It is the
        only rider type that pushes regardless."""
        config = NotificationService.CHANNEL_CONFIG[NotificationType.DELIVERY_AVAILABLE]
        assert config.get("always_push") is True

    def test_riders_are_never_emailed_about_a_job(self):
        """Email is for records, not for something with minutes on it."""
        from app.notifications.services import DeliveryChannel

        config = NotificationService.CHANNEL_CONFIG[NotificationType.DELIVERY_AVAILABLE]
        assert DeliveryChannel.EMAIL not in config["channels"]

    def test_a_placeholder_with_nothing_behind_it_does_not_lose_the_message(self):
        """It used to raise KeyError, which every caller swallows -- so one
        template gaining a field made its notifications vanish rather than
        read oddly."""
        from app.notifications.services import _Blanks

        assert (
            "You're on delivery {reference}. {pickup}".format_map(
                _Blanks({"reference": "ASG_1"})
            )
            == "You're on delivery ASG_1. "
        )


class TestNearbyAlerts:
    def test_riders_out_of_range_are_not_woken(self):
        from app.deliveries.rider_alerts import ALERT_RADIUS_KM
        from app.libs.geo import haversine_km

        # Ibadan shop, Lagos rider.
        assert haversine_km(7.4430, 3.9500, 6.5244, 3.3792) > ALERT_RADIUS_KM

    def test_one_order_cannot_wake_a_whole_city(self):
        from app.deliveries.rider_alerts import MAX_RIDERS_ALERTED

        assert MAX_RIDERS_ALERTED <= 50

    def test_an_order_that_cannot_be_read_alerts_nobody_and_does_not_raise(self):
        """It runs after a payment has committed, where nothing may fail."""
        from app.deliveries import rider_alerts

        with patch.object(rider_alerts, "read_scope", side_effect=RuntimeError("db")):
            assert rider_alerts.alert_nearby_riders("ORD_1") == 0
