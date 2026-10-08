"""What a reporter hears back.

Reporting something and then never hearing anything is how people stop
reporting -- they assume nobody looked. MODERATION_ACTION existed as a type,
a template and a channel config, with nothing anywhere creating one.
"""

import pytest

from app.moderation.models import ReportStatus
from app.moderation.services import ModerationService
from app.notifications.models import NotificationType


@pytest.fixture
def captured(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.notifications.services.NotificationService.create_notification",
        lambda **kw: calls.append(kw),
    )
    return calls


class TestReporterIsTold:
    @pytest.mark.parametrize("status", [ReportStatus.ACTIONED, ReportStatus.DISMISSED])
    def test_a_decision_reaches_the_reporter(self, captured, status):
        ModerationService._notify_reporter("USR_1", "RPT_1", status, None)
        assert len(captured) == 1
        call = captured[0]
        assert call["notification_type"] is NotificationType.MODERATION_ACTION
        assert call["user_id"] == "USR_1"
        assert call["reference_id"] == "RPT_1"

    def test_the_message_says_what_happened_in_plain_words(self, captured):
        ModerationService._notify_reporter(
            "USR_1", "RPT_1", ReportStatus.ACTIONED, None
        )
        action = captured[0]["metadata_"]["action_type"]
        assert "reported" in action
        # Not the raw enum value.
        assert action != "actioned"

    def test_dismissed_says_the_content_stayed_up(self, captured):
        ModerationService._notify_reporter(
            "USR_1", "RPT_1", ReportStatus.DISMISSED, None
        )
        assert "left it up" in captured[0]["metadata_"]["action_type"]

    def test_the_outcome_does_not_describe_the_other_person(self, captured):
        # What happened to whoever was reported is between us and them.
        for status in (ReportStatus.ACTIONED, ReportStatus.DISMISSED):
            captured.clear()
            ModerationService._notify_reporter("USR_1", "RPT_1", status, None)
            action = captured[0]["metadata_"]["action_type"].lower()
            for leak in ("banned", "suspended", "warned", "removed the user"):
                assert leak not in action

    def test_a_failed_notification_does_not_break_moderation(self, monkeypatch):
        monkeypatch.setattr(
            "app.notifications.services.NotificationService.create_notification",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("down")),
        )
        ModerationService._notify_reporter(
            "USR_1", "RPT_1", ReportStatus.ACTIONED, None
        )


class TestTemplateRendersIt:
    def test_the_message_is_the_outcome_itself(self):
        from app.notifications.services import NotificationService

        template = NotificationService.TEMPLATES[NotificationType.MODERATION_ACTION]
        rendered = template["message"].format(
            action_type="We took action on the content you reported"
        )
        # Not "A moderation action was taken: we took action on..."
        assert rendered == "We took action on the content you reported"
