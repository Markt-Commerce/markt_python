"""Completeness tests for NotificationService's TEMPLATES/CHANNEL_CONFIG
dicts. Real bug class caught while wiring Phase 12 (15): a NotificationType
with no TEMPLATES entry raises ValueError on every real call (never
caught by any test that mocks create_notification itself, e.g.
THIN_VOLUME_DELIVERY_CHOICE, added in Phase 9); a type with no
CHANNEL_CONFIG entry silently falls back to WEBSOCKET-only delivery --
no push, no email -- even if the buyer isn't actively connected at that
moment (e.g. ITEM_UNFULFILLED/ORDER_CANCELLED/DELIVERY_FAILED/
REFUND_ISSUED, added in this same phase). Neither gap raises anywhere
except at the exact moment a real (non-mocked) delivery is attempted."""

from app.notifications.models import NotificationType
from app.notifications.services import NotificationService


def test_every_notification_type_has_a_template():
    """A missing entry here isn't cosmetic -- create_notification raises
    ValueError for it on every real call."""
    missing = [t for t in NotificationType if t not in NotificationService.TEMPLATES]
    assert not missing, f"NotificationType(s) missing a TEMPLATES entry: {missing}"


def test_every_template_has_title_and_message():
    for notification_type, template in NotificationService.TEMPLATES.items():
        assert "title" in template, f"{notification_type} template missing 'title'"
        assert "message" in template, f"{notification_type} template missing 'message'"


def test_phase_12_notification_types_configure_push_delivery():
    """These four are buyer-facing events about something that already
    happened while the buyer was very likely not looking at the app --
    unlike some purely in-app/seller-only types, they must not silently
    fall back to WEBSOCKET-only."""
    for notification_type in (
        NotificationType.ITEM_UNFULFILLED,
        NotificationType.ORDER_CANCELLED,
        NotificationType.DELIVERY_FAILED,
        NotificationType.REFUND_ISSUED,
    ):
        config = NotificationService.CHANNEL_CONFIG.get(notification_type)
        assert config is not None, f"{notification_type} has no CHANNEL_CONFIG entry"
        from app.notifications.services import DeliveryChannel

        assert DeliveryChannel.PUSH in config.get("channels", [])
