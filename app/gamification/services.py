"""Gamification business logic: award points, maintain stats, evaluate badges,
and build the read models the API returns.

Coupling is one-directional: this module reads from existing tables (orders,
posts, reviews) to compute badge stats, but existing code never imports from
here — it only emits domain signals that events.py listens to.
"""

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from external.database import db
from external.redis import redis_client
from app.libs.session import session_scope

from . import leaderboard, tier_engine, badge_engine
from .constants import (
    POINT_VALUES,
    DAILY_CAPS,
    DEFAULT_TIER_KEY,
    TIER_SEED,
    GAMIFICATION_LAUNCH_DATE,
    EARLY_BIRD_WINDOW_DAYS,
    ratelimit_key,
    stats_cache_key,
    STATS_CACHE_TTL_SECONDS,
    LB_SCOPE_GLOBAL,
)
from .models import (
    PointsLedger,
    UserStats,
    SellerStats,
    Badge,
    UserBadge,
    TierConfig,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Tier config cache
# --------------------------------------------------------------------------- #
_tier_cache = {"rows": None, "ts": 0.0}
_TIER_CACHE_TTL = 300


def _tier_rows():
    now = datetime.utcnow().timestamp()
    if _tier_cache["rows"] and now - _tier_cache["ts"] < _TIER_CACHE_TTL:
        return _tier_cache["rows"]
    try:
        with session_scope() as session:
            rows = [
                {
                    "tier": t.tier,
                    "name": t.name,
                    "star_count": t.star_count,
                    "min_lifetime_points": t.min_lifetime_points,
                    "color_hex": t.color_hex,
                }
                for t in session.query(TierConfig).all()
            ]
        if not rows:
            rows = list(TIER_SEED)
    except Exception as e:  # pragma: no cover - fall back to seed
        logger.warning(f"tier config load failed, using seed: {e}")
        rows = list(TIER_SEED)
    _tier_cache["rows"] = rows
    _tier_cache["ts"] = now
    return rows


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _today_str() -> str:
    return datetime.utcnow().strftime("%Y%m%d")


def _get_or_create_stats(session, user_id: str) -> UserStats:
    stats = (
        session.query(UserStats).filter_by(user_id=user_id).with_for_update().first()
    )
    if stats is None:
        stats = UserStats(
            user_id=user_id,
            lifetime_points=0,
            available_points=0,
            weekly_points=0,
            weekly_period=leaderboard.current_week_key(),
            current_tier=DEFAULT_TIER_KEY,
        )
        session.add(stats)
        session.flush()
    return stats


def _user_roles(session, user_id: str):
    """(is_buyer, is_seller) for leaderboard scope routing."""
    from app.users.models import User

    user = session.query(User).get(user_id)
    if not user:
        return (False, False)
    return (bool(user.is_buyer), bool(user.is_seller))


def _within_daily_cap(reason: str, user_id: str) -> bool:
    cap = DAILY_CAPS.get(reason)
    if cap is None:
        return True
    try:
        key = ratelimit_key(reason, user_id, _today_str())
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, 60 * 60 * 48)  # 2 days, covers TZ edges
        return count <= cap
    except Exception:
        # If Redis is unavailable, fail open (award) — better than losing points.
        return True


def _invalidate_stats_cache(user_id: str) -> None:
    try:
        redis_client.delete(stats_cache_key(user_id))
    except Exception:
        pass


def _emit(user_id: str, event: str, data: dict) -> None:
    try:
        from main.sockets import emit_to_user

        emit_to_user(user_id, event, data, namespace="/notification")
    except Exception as e:  # pragma: no cover - realtime best-effort
        logger.debug(f"gamification emit {event} failed for {user_id}: {e}")


def _push(user_id: str, title: str, body: str, data: dict = None) -> None:
    """Best-effort remote push so gamification wins reach a closed app."""
    try:
        from app.notifications.services import PushService

        PushService.send_to_user(user_id, title, body, data or {})
    except Exception as e:  # pragma: no cover - push best-effort
        logger.debug(f"gamification push failed for {user_id}: {e}")


# --------------------------------------------------------------------------- #
# Core: award / reverse points
# --------------------------------------------------------------------------- #
def award_points(
    user_id, delta, reason, ref_type=None, ref_id=None, emit=True, enforce_cap=True
):
    """Atomically write a ledger row, update running totals, recompute tier, then
    (post-commit) update Redis and emit realtime events.

    Idempotent: a duplicate (user_id, reason, ref_type, ref_id) is a no-op,
    guarded both by a pre-check and by the ledger's unique partial index.
    Returns a small result dict, or None if skipped (duplicate or capped).
    """
    if not user_id or delta == 0:
        return None

    ref_id_s = None if ref_id is None else str(ref_id)

    # Daily anti-abuse cap (only for positive, capped reasons).
    if enforce_cap and delta > 0 and reason in DAILY_CAPS:
        if not _within_daily_cap(reason, user_id):
            return None

    result = None
    try:
        with session_scope() as session:
            # Short-circuit idempotency check.
            if ref_id_s is not None:
                dup = (
                    session.query(PointsLedger.id)
                    .filter_by(
                        user_id=user_id,
                        reason=reason,
                        ref_type=ref_type,
                        ref_id=ref_id_s,
                    )
                    .first()
                )
                if dup:
                    return None

            stats = _get_or_create_stats(session, user_id)

            # Weekly rollover.
            wk = leaderboard.current_week_key()
            if stats.weekly_period != wk:
                stats.weekly_period = wk
                stats.weekly_points = 0

            stats.lifetime_points = (stats.lifetime_points or 0) + delta
            stats.available_points = (stats.available_points or 0) + delta
            stats.weekly_points = (stats.weekly_points or 0) + delta

            old_tier = stats.current_tier
            new_tier = tier_engine.tier_key_for(stats.lifetime_points, _tier_rows())
            stats.current_tier = new_tier

            ledger = PointsLedger(
                user_id=user_id,
                delta=delta,
                reason=reason,
                ref_type=ref_type,
                ref_id=ref_id_s,
                balance_after=stats.available_points,
            )
            session.add(ledger)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()  # concurrent duplicate lost the race
                return None

            is_buyer, is_seller = _user_roles(session, user_id)
            result = {
                "delta": delta,
                "reason": reason,
                "new_balance": stats.available_points,
                "lifetime_points": stats.lifetime_points,
                "weekly_points": stats.weekly_points,
                "old_tier": old_tier,
                "new_tier": new_tier,
                "is_buyer": is_buyer,
                "is_seller": is_seller,
                "star_count": _stars_for(new_tier),
            }
    except IntegrityError:
        return None
    except Exception as e:
        logger.error(f"award_points failed ({reason}, {user_id}): {e}")
        return None

    if not result:
        return None

    # Post-commit: Redis leaderboard + cache invalidation + realtime.
    leaderboard.apply_award(
        user_id,
        delta,
        result["lifetime_points"],
        result["weekly_points"],
        result["is_buyer"],
        result["is_seller"],
    )
    _invalidate_stats_cache(user_id)

    if emit:
        _emit(
            user_id,
            "gamification:points_awarded",
            {
                "delta": delta,
                "reason": reason,
                "new_balance": result["new_balance"],
            },
        )
        if result["new_tier"] != result["old_tier"]:
            _emit(
                user_id,
                "gamification:tier_changed",
                {
                    "old_tier": result["old_tier"],
                    "new_tier": result["new_tier"],
                    "stars": result["star_count"],
                },
            )
            _push(
                user_id,
                "Level up! 🌟",
                f"You reached a new tier — {result['star_count']}★.",
                {"type": "tier_changed", "new_tier": result["new_tier"]},
            )
    return result


def award_by_reason(user_id, reason, ref_type=None, ref_id=None, **kw):
    """Award the configured point value for a reason key (Appendix A)."""
    delta = POINT_VALUES.get(reason)
    if delta is None:
        logger.warning(f"award_by_reason: unknown reason '{reason}'")
        return None
    return award_points(user_id, delta, reason, ref_type=ref_type, ref_id=ref_id, **kw)


def reverse_award(user_id, reason, ref_type, ref_id, reversal_reason):
    """Claw back a prior award with a negative ledger entry (spec §4.1).

    Looks up the original positive award(s) for (reason, ref) and writes the
    negated total. Idempotent on the reversal ref.
    """
    if not user_id:
        return None
    ref_id_s = None if ref_id is None else str(ref_id)
    with session_scope() as session:
        original = (
            session.query(PointsLedger)
            .filter_by(
                user_id=user_id, reason=reason, ref_type=ref_type, ref_id=ref_id_s
            )
            .first()
        )
        if not original or original.delta <= 0:
            return None
        already = (
            session.query(PointsLedger.id)
            .filter_by(
                user_id=user_id,
                reason=reversal_reason,
                ref_type=ref_type,
                ref_id=ref_id_s,
            )
            .first()
        )
        if already:
            return None
    return award_points(
        user_id,
        -original.delta,
        reversal_reason,
        ref_type=ref_type,
        ref_id=ref_id,
        enforce_cap=False,
    )


def _stars_for(tier_key: str) -> int:
    for row in _tier_rows():
        if row["tier"] == tier_key:
            return row["star_count"]
    return 0


# --------------------------------------------------------------------------- #
# Seller stats maintenance
# --------------------------------------------------------------------------- #
def _get_or_create_seller_stats(session, user_id: str) -> SellerStats:
    ss = session.query(SellerStats).filter_by(user_id=user_id).with_for_update().first()
    if ss is None:
        ss = SellerStats(user_id=user_id)
        session.add(ss)
        session.flush()
    return ss


def record_sale(user_id: str, ship_hours: float = None, on_time: bool = None) -> None:
    """Increment a seller's completed-sales aggregates (order.completed)."""
    with session_scope() as session:
        ss = _get_or_create_seller_stats(session, user_id)
        ss.total_sales = (ss.total_sales or 0) + 1
        if ship_hours is not None:
            ss.ship_count = (ss.ship_count or 0) + 1
            ss.ship_hours_sum = (ss.ship_hours_sum or 0.0) + float(ship_hours)
            if on_time:
                ss.on_time_count = (ss.on_time_count or 0) + 1
            ss.avg_ship_hours = ss.ship_hours_sum / ss.ship_count
            ss.on_time_pct = (ss.on_time_count or 0) / ss.ship_count * 100.0


def record_review(user_id: str, rating: float) -> None:
    """Fold a new review rating into a seller's average (review.created)."""
    with session_scope() as session:
        ss = _get_or_create_seller_stats(session, user_id)
        ss.review_count = (ss.review_count or 0) + 1
        ss.rating_sum = (ss.rating_sum or 0.0) + float(rating)
        ss.avg_rating = round(ss.rating_sum / ss.review_count, 3)


# --------------------------------------------------------------------------- #
# Badge stats + evaluation
# --------------------------------------------------------------------------- #
def get_badge_stats(user_id: str) -> dict:
    """Assemble the flat stats dict badge_engine evaluates against.

    Seller aggregates come from gam_seller_stats; buyer/community stats are
    computed on demand. Each cross-module lookup is guarded so a schema quirk
    degrades a single stat rather than breaking evaluation.
    """
    stats = {
        "total_sales": 0,
        "avg_rating": 0.0,
        "avg_ship_hours": None,
        "on_time_pct": 0.0,
        "review_count": 0,
        "is_verified_seller": 0,
        "is_early_member": 0,
        "completed_purchases": 0,
        "max_same_seller_purchases": 0,
        "total_reactions_received": 0,
        "best_post_driven_orders": 0,
    }
    with session_scope() as session:
        ss = session.query(SellerStats).filter_by(user_id=user_id).first()
        if ss:
            stats.update(
                {
                    "total_sales": ss.total_sales or 0,
                    "avg_rating": ss.avg_rating or 0.0,
                    "avg_ship_hours": ss.avg_ship_hours,
                    "on_time_pct": ss.on_time_pct or 0.0,
                    "review_count": ss.review_count or 0,
                }
            )

        from app.users.models import User

        user = session.query(User).get(user_id)
        if user:
            # Verified seller.
            try:
                from app.users.models import SellerVerificationStatus

                sa = user.seller_account
                if sa and sa.verification_status == SellerVerificationStatus.VERIFIED:
                    stats["is_verified_seller"] = 1
            except Exception:
                pass
            # Early bird.
            try:
                launch = datetime.strptime(GAMIFICATION_LAUNCH_DATE, "%Y-%m-%d")
                cutoff = launch + timedelta(days=EARLY_BIRD_WINDOW_DAYS)
                if user.created_at and user.created_at <= cutoff:
                    stats["is_early_member"] = 1
            except Exception:
                pass
            # Buyer purchase stats.
            try:
                if user.buyer_account:
                    _fill_buyer_stats(session, user.buyer_account.id, stats)
            except Exception as e:
                logger.debug(f"buyer stats skipped for {user_id}: {e}")
            # Community reactions (likes across the user's posts).
            try:
                stats["total_reactions_received"] = _count_post_reactions(
                    session, user_id
                )
            except Exception as e:
                logger.debug(f"reaction stats skipped for {user_id}: {e}")
    return stats


def _fill_buyer_stats(session, buyer_id: int, stats: dict) -> None:
    from sqlalchemy import func
    from app.orders.models import Order, OrderStatus

    completed = (
        session.query(func.count(Order.id))
        .filter(Order.buyer_id == buyer_id, Order.status == OrderStatus.DELIVERED)
        .scalar()
    ) or 0
    stats["completed_purchases"] = int(completed)

    # Max purchases from a single seller (repeat_customer). Counts distinct
    # delivered orders per seller via order items.
    from app.orders.models import OrderItem

    rows = (
        session.query(
            OrderItem.seller_id, func.count(func.distinct(OrderItem.order_id))
        )
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.buyer_id == buyer_id, Order.status == OrderStatus.DELIVERED)
        .group_by(OrderItem.seller_id)
        .all()
    )
    stats["max_same_seller_purchases"] = max((c for _, c in rows), default=0)


def _count_post_reactions(session, user_id: str) -> int:
    from sqlalchemy import func
    from app.socials.models import Post, PostLike

    count = (
        session.query(func.count(PostLike.id))
        .join(Post, Post.id == PostLike.post_id)
        .filter(Post.user_id == user_id)
        .scalar()
    )
    return int(count or 0)


def evaluate_badges_for(user_id: str, trigger: str) -> list:
    """Re-evaluate every active badge whose trigger includes `trigger`.

    Awards any newly-satisfied badge (idempotent on the unique (user, badge)
    constraint) and emits badge_earned. Returns the list of newly-awarded slugs.
    """
    if not user_id:
        return []

    stats = get_badge_stats(user_id)
    newly = []
    with session_scope() as session:
        candidates = session.query(Badge).filter(Badge.is_active.is_(True)).all()
        held = {
            ub.badge_id
            for ub in session.query(UserBadge.badge_id).filter_by(user_id=user_id).all()
        }
        for badge in candidates:
            criteria = badge.criteria_json or {}
            if trigger not in badge_engine.triggers(criteria):
                continue
            if badge.id in held:
                continue
            if not badge_engine.evaluate(criteria, stats):
                continue
            ub = UserBadge(
                user_id=user_id, badge_id=badge.id, progress_json={"met": True}
            )
            session.add(ub)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                continue
            newly.append(badge)

    for badge in newly:
        _emit(
            user_id,
            "gamification:badge_earned",
            {
                "badge": {
                    "slug": badge.slug,
                    "name": badge.name,
                    "icon_url": badge.icon_url,
                    "description": badge.description,
                }
            },
        )
        _push(
            user_id,
            "Badge unlocked! 🎉",
            f"You earned the {badge.name} badge.",
            {"type": "badge_earned", "slug": badge.slug},
        )
    if newly:
        _invalidate_stats_cache(user_id)
    return [b.slug for b in newly]


# --------------------------------------------------------------------------- #
# Read models (for routes)
# --------------------------------------------------------------------------- #
def get_me(user_id: str) -> dict:
    with session_scope() as session:
        stats = session.query(UserStats).filter_by(user_id=user_id).first()
        lifetime = stats.lifetime_points if stats else 0
        available = stats.available_points if stats else 0
        weekly = stats.weekly_points if stats else 0
        earned = session.query(UserBadge).filter_by(user_id=user_id).count()
        total_badges = session.query(Badge).filter(Badge.is_active.is_(True)).count()
        opt_out = _get_opt_out(session, user_id)

    prog = tier_engine.tier_progress(lifetime, _tier_rows())
    rank = leaderboard.get_user_rank(LB_SCOPE_GLOBAL, "weekly", user_id)

    return {
        "user_id": user_id,
        "lifetime_points": lifetime,
        "available_points": available,
        "weekly_points": weekly,
        "tier": _tier_payload(prog),
        "badges_earned": earned,
        "badges_total": total_badges,
        "weekly_rank": (
            {"scope": "global", "rank": rank["rank"], "out_of": rank["out_of"]}
            if rank
            else None
        ),
        "opt_out_leaderboard": opt_out,
    }


def get_public_profile(user_id: str) -> dict:
    with session_scope() as session:
        stats = session.query(UserStats).filter_by(user_id=user_id).first()
        lifetime = stats.lifetime_points if stats else 0
        badges = _user_badges_payload(session, user_id)
    prog = tier_engine.tier_progress(lifetime, _tier_rows())
    return {
        "user_id": user_id,
        "lifetime_points": lifetime,
        "tier": _tier_payload(prog),
        "badges": badges,
    }


def get_points_history(user_id: str, cursor: int = None, limit: int = 20) -> dict:
    limit = max(1, min(limit, 100))
    with session_scope() as session:
        q = session.query(PointsLedger).filter_by(user_id=user_id)
        if cursor:
            q = q.filter(PointsLedger.id < cursor)
        rows = q.order_by(PointsLedger.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "id": r.id,
                "delta": r.delta,
                "reason": r.reason,
                "ref_type": r.ref_type,
                "ref_id": r.ref_id,
                "balance_after": r.balance_after,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "next_cursor": rows[-1].id if (has_more and rows) else None,
    }


def get_badge_catalog() -> list:
    with session_scope() as session:
        badges = (
            session.query(Badge)
            .filter(Badge.is_active.is_(True))
            .order_by(Badge.priority.desc())
            .all()
        )
        return [_badge_payload(b) for b in badges]


def get_user_badges(user_id: str) -> dict:
    stats = get_badge_stats(user_id)
    with session_scope() as session:
        active = (
            session.query(Badge)
            .filter(Badge.is_active.is_(True))
            .order_by(Badge.priority.desc())
            .all()
        )
        held = {
            ub.badge_id: ub
            for ub in session.query(UserBadge).filter_by(user_id=user_id).all()
        }
        items = []
        for b in active:
            ub = held.get(b.id)
            items.append(
                {
                    **_badge_payload(b),
                    "earned": ub is not None,
                    "awarded_at": ub.awarded_at if ub else None,
                    "progress": (
                        1.0
                        if ub
                        else badge_engine.progress(b.criteria_json or {}, stats)
                    ),
                }
            )
    return {"items": items}


def get_tiers() -> list:
    return _tier_rows()


def get_leaderboard(
    scope: str, period: str, limit: int = 50, cursor: int = None, user_id: str = None
) -> dict:
    offset = int(cursor or 0)
    limit = max(1, min(limit, 100))
    rows = leaderboard.get_page(scope, period, limit=limit, offset=offset)

    # Hydrate light user identity for display.
    ids = [r["user_id"] for r in rows]
    identities = _identities_for(ids)
    for r in rows:
        r.update(identities.get(r["user_id"], {}))

    your_rank = None
    if user_id:
        your_rank = leaderboard.get_user_rank(scope, period, user_id)

    return {
        "scope": scope,
        "period": period,
        "items": rows,
        "next_cursor": offset + limit if len(rows) == limit else None,
        "your_rank": your_rank,
    }


def set_preferences(user_id: str, opt_out_leaderboard: bool = None) -> dict:
    with session_scope() as session:
        if opt_out_leaderboard is not None:
            _set_opt_out(session, user_id, opt_out_leaderboard)
    if opt_out_leaderboard is not None:
        leaderboard.set_opt_out(user_id, opt_out_leaderboard)
    return {"opt_out_leaderboard": _get_opt_out_uncached(user_id)}


# --------------------------------------------------------------------------- #
# Preference storage (Redis-backed flag; no schema change needed for MVP)
# --------------------------------------------------------------------------- #
_OPTOUT_FLAG = "gam:pref:optout"


def _set_opt_out(session, user_id: str, value: bool) -> None:
    try:
        if value:
            redis_client.sadd(_OPTOUT_FLAG, user_id)
        else:
            redis_client.srem(_OPTOUT_FLAG, user_id)
    except Exception:
        pass


def _get_opt_out(session, user_id: str) -> bool:
    return _get_opt_out_uncached(user_id)


def _get_opt_out_uncached(user_id: str) -> bool:
    try:
        return bool(redis_client.client.sismember(_OPTOUT_FLAG, user_id))
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Payload helpers
# --------------------------------------------------------------------------- #
def _tier_payload(prog: dict) -> dict:
    cur = prog["current"]
    return {
        "key": cur["tier"],
        "name": cur["name"],
        "stars": cur["star_count"],
        "color_hex": cur["color_hex"],
        "progress_to_next": prog["progress_to_next"],
        "points_to_next_tier": prog["points_to_next_tier"],
    }


def _badge_payload(b: Badge) -> dict:
    return {
        "slug": b.slug,
        "name": b.name,
        "description": b.description,
        "icon_url": b.icon_url,
        "category": b.category,
        "audience": b.audience,
        "priority": b.priority,
    }


def _user_badges_payload(session, user_id: str) -> list:
    rows = (
        session.query(UserBadge, Badge)
        .join(Badge, Badge.id == UserBadge.badge_id)
        .filter(UserBadge.user_id == user_id)
        .order_by(Badge.priority.desc())
        .all()
    )
    return [{**_badge_payload(b), "awarded_at": ub.awarded_at} for ub, b in rows]


def _identities_for(user_ids: list) -> dict:
    if not user_ids:
        return {}
    out = {}
    try:
        with session_scope() as session:
            from app.users.models import User

            users = session.query(User).filter(User.id.in_(user_ids)).all()
            stats = {
                s.user_id: s.current_tier
                for s in session.query(UserStats)
                .filter(UserStats.user_id.in_(user_ids))
                .all()
            }
            for u in users:
                out[u.id] = {
                    "username": u.username,
                    "profile_picture": u.profile_picture,
                    "tier": stats.get(u.id, DEFAULT_TIER_KEY),
                    "stars": _stars_for(stats.get(u.id, DEFAULT_TIER_KEY)),
                }
    except Exception as e:
        logger.debug(f"identity hydrate failed: {e}")
    return out
