"""Gamification MVP: points ledger, stats, badges, tiers, leaderboard snapshots.

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.gamification.constants import TIER_SEED, BADGE_SEED

revision = "e1f2a3b4c5d6"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _table_exists("gam_points_ledger"):
        op.create_table(
            "gam_points_ledger",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(length=12),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column("delta", sa.Integer(), nullable=False),
            sa.Column("reason", sa.String(length=64), nullable=False),
            sa.Column("ref_type", sa.String(length=32), nullable=True),
            sa.Column("ref_id", sa.String(length=64), nullable=True),
            sa.Column(
                "balance_after", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_gam_points_ledger_user_id", "gam_points_ledger", ["user_id"]
        )
        op.create_index(
            "ix_gam_ledger_user_created", "gam_points_ledger", ["user_id", "created_at"]
        )
        op.create_index(
            "ix_gam_ledger_ref", "gam_points_ledger", ["ref_type", "ref_id"]
        )
        op.create_index(
            "uq_gam_ledger_idempotency",
            "gam_points_ledger",
            ["user_id", "reason", "ref_type", "ref_id"],
            unique=True,
            postgresql_where=sa.text("ref_id IS NOT NULL"),
        )

    if not _table_exists("gam_user_stats"):
        op.create_table(
            "gam_user_stats",
            sa.Column(
                "user_id",
                sa.String(length=12),
                sa.ForeignKey("users.id"),
                primary_key=True,
            ),
            sa.Column(
                "lifetime_points", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "available_points", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "weekly_points", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("weekly_period", sa.String(length=8), nullable=True),
            sa.Column(
                "current_tier",
                sa.String(length=20),
                nullable=False,
                server_default="newcomer",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not _table_exists("gam_seller_stats"):
        op.create_table(
            "gam_seller_stats",
            sa.Column(
                "user_id",
                sa.String(length=12),
                sa.ForeignKey("users.id"),
                primary_key=True,
            ),
            sa.Column("total_sales", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rating_sum", sa.Float(), nullable=False, server_default="0"),
            sa.Column("avg_rating", sa.Float(), nullable=False, server_default="0"),
            sa.Column("ship_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ship_hours_sum", sa.Float(), nullable=False, server_default="0"),
            sa.Column(
                "on_time_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("avg_ship_hours", sa.Float(), nullable=True),
            sa.Column("on_time_pct", sa.Float(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not _table_exists("gam_badges"):
        op.create_table(
            "gam_badges",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("slug", sa.String(length=64), nullable=False, unique=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("icon_url", sa.String(length=255), nullable=True),
            sa.Column("category", sa.String(length=32), nullable=True),
            sa.Column(
                "audience", sa.String(length=2), nullable=False, server_default="BS"
            ),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("criteria_json", sa.JSON(), nullable=False),
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not _table_exists("gam_user_badges"):
        op.create_table(
            "gam_user_badges",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(length=12),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "badge_id", sa.Integer(), sa.ForeignKey("gam_badges.id"), nullable=False
            ),
            sa.Column("awarded_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("progress_json", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("user_id", "badge_id", name="uq_gam_user_badge"),
        )
        op.create_index("ix_gam_user_badges_user_id", "gam_user_badges", ["user_id"])

    if not _table_exists("gam_tier_config"):
        op.create_table(
            "gam_tier_config",
            sa.Column("tier", sa.String(length=20), primary_key=True),
            sa.Column("name", sa.String(length=50), nullable=False),
            sa.Column("min_lifetime_points", sa.Integer(), nullable=False),
            sa.Column("color_hex", sa.String(length=7), nullable=False),
            sa.Column("star_count", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not _table_exists("gam_leaderboard_snapshot"):
        op.create_table(
            "gam_leaderboard_snapshot",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("scope", sa.String(length=20), nullable=False),
            sa.Column("period_key", sa.String(length=20), nullable=False),
            sa.Column(
                "user_id",
                sa.String(length=12),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("points", sa.Integer(), nullable=False),
            sa.Column("captured_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_gam_lb_snapshot_scope_period_rank",
            "gam_leaderboard_snapshot",
            ["scope", "period_key", "rank"],
        )

    _seed()


def _seed():
    now = datetime.utcnow()

    tier_table = sa.table(
        "gam_tier_config",
        sa.column("tier", sa.String),
        sa.column("name", sa.String),
        sa.column("min_lifetime_points", sa.Integer),
        sa.column("color_hex", sa.String),
        sa.column("star_count", sa.Integer),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    bind = op.get_bind()
    existing_tiers = {
        r[0] for r in bind.execute(sa.text("SELECT tier FROM gam_tier_config"))
    }
    tier_rows = [
        {**t, "created_at": now, "updated_at": now}
        for t in TIER_SEED
        if t["tier"] not in existing_tiers
    ]
    if tier_rows:
        op.bulk_insert(tier_table, tier_rows)

    badge_table = sa.table(
        "gam_badges",
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("icon_url", sa.String),
        sa.column("category", sa.String),
        sa.column("audience", sa.String),
        sa.column("priority", sa.Integer),
        sa.column("criteria_json", sa.JSON),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    existing_badges = {
        r[0] for r in bind.execute(sa.text("SELECT slug FROM gam_badges"))
    }
    badge_rows = []
    for b in BADGE_SEED:
        if b["slug"] in existing_badges:
            continue
        badge_rows.append(
            {
                "slug": b["slug"],
                "name": b["name"],
                "description": b.get("description"),
                "icon_url": b.get("icon_url"),
                "category": b.get("category"),
                "audience": b.get("audience", "BS"),
                "priority": b.get("priority", 0),
                "criteria_json": b["criteria_json"],
                "is_active": b.get("is_active", True),
                "created_at": now,
                "updated_at": now,
            }
        )
    if badge_rows:
        op.bulk_insert(badge_table, badge_rows)


def downgrade():
    for tbl in (
        "gam_leaderboard_snapshot",
        "gam_user_badges",
        "gam_badges",
        "gam_seller_stats",
        "gam_user_stats",
        "gam_points_ledger",
        "gam_tier_config",
    ):
        if _table_exists(tbl):
            op.drop_table(tbl)
