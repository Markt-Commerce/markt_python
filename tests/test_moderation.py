"""Tests for trust & safety: content reports and user blocks.

App Store Review Guideline 1.2 requires both for apps carrying UGC, so these
cover the behaviour a reviewer would actually exercise.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import NotFoundError, ValidationError
from app.moderation.models import ReportedContentType, ReportReason, ReportStatus
from app.moderation.services import ModerationService
from app.socials.services import FeedService


def _session(existing_report=None):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = (
        existing_report
    )
    return session


@patch.object(ModerationService, "_assert_content_exists")
@patch("app.moderation.services.session_scope")
def test_report_creates_a_pending_report(mock_scope, _mock_exists):
    session = _session(existing_report=None)
    mock_scope.return_value.__enter__.return_value = session

    result = ModerationService.report_content(
        "USR_A", "post", "PST_1", "harassment", "they keep messaging me"
    )

    assert result["already_reported"] is False
    assert result["status"] == ReportStatus.PENDING.value
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.reporter_id == "USR_A"
    assert added.content_type is ReportedContentType.POST
    assert added.reason is ReportReason.HARASSMENT


@patch.object(ModerationService, "_assert_content_exists")
@patch("app.moderation.services.session_scope")
def test_reporting_twice_is_idempotent(mock_scope, _mock_exists):
    """A second tap must not create a second row -- otherwise a single user can
    inflate the moderation queue on their own."""
    existing = SimpleNamespace(id="RPT_1", status=ReportStatus.PENDING)
    session = _session(existing_report=existing)
    mock_scope.return_value.__enter__.return_value = session

    result = ModerationService.report_content("USR_A", "post", "PST_1", "spam")

    assert result["already_reported"] is True
    assert result["report_id"] == "RPT_1"
    session.add.assert_not_called()


@patch.object(ModerationService, "_assert_content_exists")
@patch("app.moderation.services.session_scope")
def test_report_rejects_unknown_reason(mock_scope, _mock_exists):
    mock_scope.return_value.__enter__.return_value = _session()
    with pytest.raises(ValidationError):
        ModerationService.report_content("USR_A", "post", "PST_1", "because-i-said-so")


@patch.object(ModerationService, "_assert_content_exists")
@patch("app.moderation.services.session_scope")
def test_cannot_report_yourself(mock_scope, _mock_exists):
    mock_scope.return_value.__enter__.return_value = _session()
    with pytest.raises(ValidationError):
        ModerationService.report_content("USR_A", "user", "USR_A", "spam")


@patch("app.moderation.services.session_scope")
def test_cannot_block_yourself(mock_scope):
    mock_scope.return_value.__enter__.return_value = _session()
    with pytest.raises(ValidationError):
        ModerationService.block_user("USR_A", "USR_A")


@patch("app.moderation.services.session_scope")
def test_blocking_a_missing_user_is_a_404(mock_scope):
    session = MagicMock()
    session.query.return_value.get.return_value = None
    mock_scope.return_value.__enter__.return_value = session
    with pytest.raises(NotFoundError):
        ModerationService.block_user("USR_A", "USR_GONE")


@patch("app.moderation.services.session_scope")
def test_blocked_ids_cover_both_directions(mock_scope):
    """If A blocks B, neither should see the other in their feed -- otherwise
    B keeps interacting with A through the feed after being blocked."""
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [
        ("USR_ME", "USR_I_BLOCKED"),
        ("USR_BLOCKED_ME", "USR_ME"),
    ]
    mock_scope.return_value.__enter__.return_value = session

    ids = ModerationService.blocked_user_ids("USR_ME")

    assert ids == {"USR_I_BLOCKED", "USR_BLOCKED_ME"}


@patch("app.moderation.services.session_scope")
def test_blocked_ids_empty_for_anonymous(mock_scope):
    assert ModerationService.blocked_user_ids(None) == set()
    mock_scope.assert_not_called()


# --- feed filtering ------------------------------------------------------

FEED = [
    {"id": "PST_1", "type": "post", "user": {"id": "USR_OK"}},
    {"id": "PST_2", "type": "post", "user": {"id": "USR_BLOCKED"}},
    {
        "id": "PRD_1",
        "type": "product",
        "seller": {"id": 1, "user": {"id": "USR_BLOCKED"}},
    },
    {"id": "PRD_2", "type": "product", "seller": {"id": 2, "user": {"id": "USR_OK"}}},
]


@patch.object(ModerationService, "blocked_user_ids", return_value={"USR_BLOCKED"})
def test_feed_drops_posts_and_products_from_blocked_users(_mock):
    out = FeedService._drop_blocked_authors(FEED, "USR_ME")
    assert [i["id"] for i in out] == ["PST_1", "PRD_2"]


@patch.object(ModerationService, "blocked_user_ids", return_value=set())
def test_feed_untouched_when_nothing_blocked(_mock):
    assert FeedService._drop_blocked_authors(FEED, "USR_ME") == FEED


def test_feed_untouched_for_anonymous_viewer():
    assert FeedService._drop_blocked_authors(FEED, None) == FEED


@patch.object(ModerationService, "blocked_user_ids", side_effect=Exception("db down"))
def test_feed_fails_open_if_block_lookup_errors(_mock):
    """An unfiltered feed is a far better failure than an empty one."""
    assert FeedService._drop_blocked_authors(FEED, "USR_ME") == FEED
