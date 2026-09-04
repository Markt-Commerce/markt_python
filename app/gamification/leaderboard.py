"""Redis-backed leaderboard ranking utilities (spec 4.4, 5.4).

Live ranks live in sorted sets, updated atomically on every award. Score is the
user's points in the period (lifetime for all-time, weekly for weekly). The
buyers/sellers scopes are the same score filtered to that audience.

Opt-out: opted-out users remain in the sorted sets (so their own "your rank"
stays accurate) but are recorded in a side SET and filtered out of the public
listing.
"""

import logging
from datetime import datetime, date
from typing import List, Dict, Optional

from external.redis import redis_client
from .constants import (
    lb_key,
    LB_SCOPE_GLOBAL,
    LB_SCOPE_BUYERS,
    LB_SCOPE_SELLERS,
    LB_PERIOD_ALLTIME,
    LB_PERIOD_WEEKLY,
)

logger = logging.getLogger(__name__)

_OPTOUT_KEY = "gam:lb:optout"


def current_week_key(when: datetime = None) -> str:
    """ISO week key, e.g. '2026-W30'."""
    d = (when or datetime.utcnow()).date()
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _scopes_for(is_buyer: bool, is_seller: bool) -> List[str]:
    scopes = [LB_SCOPE_GLOBAL]
    if is_buyer:
        scopes.append(LB_SCOPE_BUYERS)
    if is_seller:
        scopes.append(LB_SCOPE_SELLERS)
    return scopes


def apply_award(
    user_id: str,
    delta: int,
    lifetime_points: int,
    weekly_points: int,
    is_buyer: bool,
    is_seller: bool,
    week_key: str = None,
) -> None:
    """Fire-and-forget ZSET update after a successful ledger commit.

    All-time sets are set to the absolute lifetime total (idempotent even if a
    prior Redis write was lost); weekly sets to the weekly total. If Redis is
    down the daily snapshot job rebuilds from SQL, so failures are swallowed.
    """
    week_key = week_key or current_week_key()
    try:
        pipe = redis_client.pipeline()
        for scope in _scopes_for(is_buyer, is_seller):
            pipe.zadd(lb_key(scope, LB_PERIOD_ALLTIME), {user_id: lifetime_points})
            pipe.zadd(
                lb_key(scope, LB_PERIOD_WEEKLY, week_key), {user_id: weekly_points}
            )
        pipe.execute()
    except Exception as e:  # pragma: no cover - Redis best-effort
        logger.warning(f"leaderboard.apply_award failed for {user_id}: {e}")


def _is_opted_out(user_id: str) -> bool:
    try:
        return redis_client.client.sismember(_OPTOUT_KEY, user_id)
    except Exception:
        return False


def set_opt_out(user_id: str, opted_out: bool) -> None:
    try:
        if opted_out:
            redis_client.sadd(_OPTOUT_KEY, user_id)
        else:
            redis_client.srem(_OPTOUT_KEY, user_id)
    except Exception as e:  # pragma: no cover
        logger.warning(f"leaderboard.set_opt_out failed for {user_id}: {e}")


def _key(scope: str, period: str, week_key: str = None) -> str:
    return lb_key(scope, period, week_key or current_week_key())


def get_page(
    scope: str, period: str, limit: int = 50, offset: int = 0, week_key: str = None
) -> List[Dict]:
    """Top-N rows for a scope/period, opted-out users filtered out.

    Ranks are the true 1-based position in the set, so hidden users leave a gap
    rather than shifting everyone up.
    """
    key = _key(scope, period, week_key)
    try:
        raw = redis_client.zrevrange(key, offset, offset + limit - 1, withscores=True)
    except Exception as e:
        logger.warning(f"leaderboard.get_page failed for {key}: {e}")
        return []

    rows = []
    for idx, (user_id, score) in enumerate(raw):
        if _is_opted_out(user_id):
            continue
        rows.append(
            {"user_id": user_id, "points": int(score), "rank": offset + idx + 1}
        )
    return rows


def get_user_rank(
    scope: str, period: str, user_id: str, week_key: str = None
) -> Optional[Dict]:
    """The user's own rank row (accurate even if opted out)."""
    key = _key(scope, period, week_key)
    try:
        rank = redis_client.client.zrevrank(key, user_id)
        if rank is None:
            return None
        score = redis_client.zscore(key, user_id)
        out_of = redis_client.zcard(key)
        return {
            "scope": scope,
            "period": period,
            "rank": rank + 1,
            "points": int(score or 0),
            "out_of": int(out_of or 0),
        }
    except Exception as e:
        logger.warning(f"leaderboard.get_user_rank failed for {key}: {e}")
        return None


def seed_member(
    scope: str, period: str, user_id: str, points: int, week_key: str = None
) -> None:
    """Used by the cold-start rebuild to load a single member."""
    try:
        redis_client.zadd(_key(scope, period, week_key), {user_id: points})
    except Exception as e:  # pragma: no cover
        logger.warning(f"leaderboard.seed_member failed: {e}")
