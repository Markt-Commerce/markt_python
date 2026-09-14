"""Gamification ORM models (all tables prefixed gam_).

Design notes (spec 5.2):
- No existing table is modified. Foreign keys point *into* users only, so the
  whole feature can be rolled forward/back independently.
- The ledger carries a unique partial index on
  (user_id, reason, ref_type, ref_id) WHERE ref_id IS NOT NULL — the single
  most important idempotency guard against double-credits.
"""

from sqlalchemy import Index, UniqueConstraint, text

from external.database import db
from app.libs.models import BaseModel


class PointsLedger(BaseModel):
    """Append-only audit of every credit/debit."""

    __tablename__ = "gam_points_ledger"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.String(12), db.ForeignKey("users.id"), nullable=False, index=True
    )
    delta = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(64), nullable=False)
    ref_type = db.Column(db.String(32), nullable=True)
    ref_id = db.Column(db.String(64), nullable=True)
    balance_after = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        # Idempotency: the same (reason, ref) can only be credited once. Partial
        # so that ad-hoc awards without a ref_id (e.g. daily login handled by a
        # separate key) are not constrained here.
        Index(
            "uq_gam_ledger_idempotency",
            "user_id",
            "reason",
            "ref_type",
            "ref_id",
            unique=True,
            postgresql_where=text("ref_id IS NOT NULL"),
        ),
        Index("ix_gam_ledger_user_created", "user_id", "created_at"),
        Index("ix_gam_ledger_ref", "ref_type", "ref_id"),
    )


class UserStats(BaseModel):
    """Denormalised running totals for fast profile reads."""

    __tablename__ = "gam_user_stats"

    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), primary_key=True)
    lifetime_points = db.Column(db.Integer, nullable=False, default=0)
    available_points = db.Column(db.Integer, nullable=False, default=0)
    weekly_points = db.Column(db.Integer, nullable=False, default=0)
    weekly_period = db.Column(db.String(8), nullable=True)  # e.g. "2026-W30"
    current_tier = db.Column(db.String(20), nullable=False, default="newcomer")

    # 15.1 celebrate-exactly-once: the last tier the client has actually shown
    # a celebration for. current_tier alone can't answer "is this new to the
    # user" -- it is already updated by the time anything reads it, and a
    # socket event is lost if the app was backgrounded. Comparing the two
    # survives a restart, a reinstall, and a second device.
    celebrated_tier = db.Column(db.String(20), nullable=True)

    # 15.2 streak. daily_login already awards points idempotently per day; this
    # counts the consecutive run so it can be shown and celebrated.
    # last_active_date is a date, not a timestamp: "did they show up today" is
    # a calendar question, and storing a time invites timezone drift into a
    # comparison that only cares about the day.
    streak_days = db.Column(db.Integer, nullable=False, default=0)
    longest_streak = db.Column(db.Integer, nullable=False, default=0)
    last_active_date = db.Column(db.Date, nullable=True)
    # The last milestone actually shown to the user, so a streak celebration
    # survives the socket the way a tier-up does. Without it the streak event
    # is emitted during the login request -- before the app has a user id, and
    # therefore before it has connected its socket -- so it is always lost on
    # the one occasion it matters most.
    celebrated_streak = db.Column(db.Integer, nullable=True)


class SellerStats(BaseModel):
    """Aggregates that feed seller badge criteria.

    Public columns (total_sales, avg_rating, avg_ship_hours, on_time_pct) are
    derived from the accumulators so averages update incrementally without a
    full recompute.
    """

    __tablename__ = "gam_seller_stats"

    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), primary_key=True)
    total_sales = db.Column(db.Integer, nullable=False, default=0)

    # Rating accumulators -> avg_rating.
    review_count = db.Column(db.Integer, nullable=False, default=0)
    rating_sum = db.Column(db.Float, nullable=False, default=0.0)
    avg_rating = db.Column(db.Float, nullable=False, default=0.0)

    # Shipping accumulators -> avg_ship_hours / on_time_pct.
    ship_count = db.Column(db.Integer, nullable=False, default=0)
    ship_hours_sum = db.Column(db.Float, nullable=False, default=0.0)
    on_time_count = db.Column(db.Integer, nullable=False, default=0)
    avg_ship_hours = db.Column(db.Float, nullable=True)
    on_time_pct = db.Column(db.Float, nullable=True)


class Badge(BaseModel):
    """Static catalog row; criteria evaluated by badge_engine."""

    __tablename__ = "gam_badges"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    icon_url = db.Column(db.String(255), nullable=True)
    category = db.Column(db.String(32), nullable=True)  # trust/performance/milestone
    audience = db.Column(db.String(2), nullable=False, default="BS")  # S/B/BS
    priority = db.Column(db.Integer, nullable=False, default=0)
    criteria_json = db.Column(db.JSON, nullable=False, default=dict)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class UserBadge(BaseModel):
    """One row per (user, badge) once earned."""

    __tablename__ = "gam_user_badges"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.String(12), db.ForeignKey("users.id"), nullable=False, index=True
    )
    badge_id = db.Column(db.Integer, db.ForeignKey("gam_badges.id"), nullable=False)
    awarded_at = db.Column(db.DateTime, server_default=db.func.now())
    progress_json = db.Column(db.JSON, nullable=True)

    # 15.1 celebrate-exactly-once. NULL means the user has never been shown
    # this unlock. Deliberately a timestamp rather than a boolean: it costs the
    # same and answers "when did they see it", which a support question about a
    # missed celebration actually needs.
    seen_at = db.Column(db.DateTime, nullable=True, index=True)

    badge = db.relationship("Badge")

    __table_args__ = (
        UniqueConstraint("user_id", "badge_id", name="uq_gam_user_badge"),
    )


class TierConfig(BaseModel):
    """Editable tier table seeded from constants.TIER_SEED."""

    __tablename__ = "gam_tier_config"

    tier = db.Column(db.String(20), primary_key=True)  # tier key
    name = db.Column(db.String(50), nullable=False)
    min_lifetime_points = db.Column(db.Integer, nullable=False)
    color_hex = db.Column(db.String(7), nullable=False)
    star_count = db.Column(db.Integer, nullable=False)


class LeaderboardSnapshot(BaseModel):
    """Daily archival snapshot; powers historical views and Redis cold-start."""

    __tablename__ = "gam_leaderboard_snapshot"

    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(20), nullable=False)
    period_key = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=False)
    rank = db.Column(db.Integer, nullable=False)
    points = db.Column(db.Integer, nullable=False)
    captured_at = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        Index("ix_gam_lb_snapshot_scope_period_rank", "scope", "period_key", "rank"),
    )
