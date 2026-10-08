"""The market's calendar day.

"Did they show up today" is a calendar question, and the answer depends on
whose calendar. The streak used `datetime.utcnow().date()`, which means the day
rolls over at **01:00 in Lagos** rather than midnight: a user opening the app at
00:30 has their visit counted against yesterday, and can lose a streak they did
not actually break.

Nigeria is UTC+1 year-round with no daylight saving, so a fixed offset is exact
rather than an approximation. This is deliberately a market constant and not
the user's device timezone -- a streak should not shift because someone flew to
London, and a device clock is user-settable, which would make streaks trivially
gameable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

# West Africa Time. No DST.
MARKET_UTC_OFFSET = timedelta(hours=1)
MARKET_TZ = timezone(MARKET_UTC_OFFSET, name="WAT")


def market_now() -> datetime:
    """Current time in the market's timezone, tz-aware."""
    return datetime.now(MARKET_TZ)


def market_today() -> date:
    """The calendar date it is *for the user*, which is what a streak counts."""
    return market_now().date()
