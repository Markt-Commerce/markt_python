"""Streaks, and celebrating an achievement exactly once.

The "seen" concept exists because a socket event is lost if the app was
backgrounded when it fired, and a local flag cannot be shared with a second
device. The server holds the acknowledgement instead.
"""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.gamification import services
from app.gamification.constants import STREAK_MILESTONES
from app.gamification.models import UserStats


def _scope(session):
    scope = MagicMock()
    scope.__enter__ = MagicMock(return_value=session)
    scope.__exit__ = MagicMock(return_value=False)
    return scope


def _stats(**kw):
    s = UserStats()
    s.user_id = "USR_1"
    s.lifetime_points = kw.get("lifetime_points", 0)
    s.streak_days = kw.get("streak_days", 0)
    s.longest_streak = kw.get("longest_streak", 0)
    s.last_active_date = kw.get("last_active_date")
    s.current_tier = kw.get("current_tier", "newcomer")
    s.celebrated_tier = kw.get("celebrated_tier")
    return s


def _advance(stats):
    session = MagicMock()
    with patch.object(
        services, "session_scope", return_value=_scope(session)
    ), patch.object(services, "_get_or_create_stats", return_value=stats), patch.object(
        services, "_invalidate_stats_cache"
    ):
        return services.advance_streak("USR_1")


# ---------------------------------------------------------------------------
# Streak
# ---------------------------------------------------------------------------


def test_first_ever_login_starts_at_one():
    stats = _stats(last_active_date=None)
    result = _advance(stats)
    assert stats.streak_days == 1
    assert result["streak_days"] == 1
    assert result["is_new_day"] is True


def test_consecutive_day_increments():
    stats = _stats(streak_days=4, last_active_date=date.today() - timedelta(days=1))
    _advance(stats)
    assert stats.streak_days == 5


def test_same_day_login_is_idempotent():
    """Logging in five times today must not award a five-day streak."""
    stats = _stats(streak_days=3, last_active_date=date.today())
    result = _advance(stats)
    assert stats.streak_days == 3
    assert result["is_new_day"] is False


def test_gap_restarts_at_one_not_zero():
    """The user *is* here today. Showing them 0 would be both wrong and
    discouraging."""
    stats = _stats(streak_days=9, last_active_date=date.today() - timedelta(days=3))
    _advance(stats)
    assert stats.streak_days == 1


def test_longest_streak_survives_a_break():
    stats = _stats(
        streak_days=9,
        longest_streak=9,
        last_active_date=date.today() - timedelta(days=3),
    )
    _advance(stats)
    assert stats.streak_days == 1
    assert stats.longest_streak == 9


def test_longest_streak_advances_with_a_new_best():
    stats = _stats(
        streak_days=9,
        longest_streak=9,
        last_active_date=date.today() - timedelta(days=1),
    )
    _advance(stats)
    assert stats.longest_streak == 10


@pytest.mark.parametrize("day", sorted(STREAK_MILESTONES)[:4])
def test_milestone_days_are_flagged(day):
    stats = _stats(
        streak_days=day - 1, last_active_date=date.today() - timedelta(days=1)
    )
    result = _advance(stats)
    assert result["streak_days"] == day
    assert result["is_milestone"] is True


def test_ordinary_day_is_not_a_milestone():
    stats = _stats(streak_days=4, last_active_date=date.today() - timedelta(days=1))
    result = _advance(stats)
    assert result["streak_days"] == 5
    assert result["is_milestone"] is False


# ---------------------------------------------------------------------------
# Celebrate exactly once
# ---------------------------------------------------------------------------


def _unseen(stats, badge_rows=()):
    session = MagicMock()
    session.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = list(
        badge_rows
    )
    session.query.return_value.filter_by.return_value.first.return_value = stats
    with patch.object(services, "session_scope", return_value=_scope(session)):
        return services.get_unseen_achievements("USR_1")


def test_first_sight_of_a_user_records_the_tier_without_celebrating():
    """celebrated_tier is NULL for every user that existed before this shipped.

    Treating NULL as "owes a celebration" would fire a tier-up at the entire
    user base on deploy.
    """
    stats = _stats(current_tier="bronze", celebrated_tier=None)
    result = _unseen(stats)
    assert result["tier_up"] is None
    assert stats.celebrated_tier == "bronze"


def test_a_real_tier_change_is_offered():
    stats = _stats(current_tier="silver", celebrated_tier="bronze", lifetime_points=500)
    with patch.object(services, "_tier_rows", return_value=[]), patch.object(
        services, "_tier_payload", return_value={"key": "silver"}
    ):
        result = _unseen(stats)
    assert result["tier_up"] is not None
    assert result["tier_up"]["from_tier"] == "bronze"
    assert result["tier_up"]["to_tier"] == "silver"


def test_an_already_celebrated_tier_is_not_offered_again():
    stats = _stats(current_tier="silver", celebrated_tier="silver")
    assert _unseen(stats)["tier_up"] is None


def test_marking_a_tier_seen_requires_it_to_still_be_current():
    """Guards a stale client acknowledging a tier the user has since passed,
    which would silently swallow the newer celebration."""
    stats = _stats(current_tier="gold", celebrated_tier="silver")
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = stats
    with patch.object(services, "session_scope", return_value=_scope(session)):
        result = services.mark_achievements_seen("USR_1", tier="silver")
    assert result["tier_marked"] is False
    assert stats.celebrated_tier == "silver"


def test_marking_the_current_tier_seen_works():
    stats = _stats(current_tier="gold", celebrated_tier="silver")
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = stats
    with patch.object(services, "session_scope", return_value=_scope(session)):
        result = services.mark_achievements_seen("USR_1", tier="gold")
    assert result["tier_marked"] is True
    assert stats.celebrated_tier == "gold"
