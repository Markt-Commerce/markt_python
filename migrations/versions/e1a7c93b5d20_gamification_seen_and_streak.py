"""feat(gamification): celebrate-exactly-once and streaks

Revision ID: e1a7c93b5d20
Revises: 49bdc993a1eb
Create Date: 2026-09-06

Adds what the app needs to celebrate an achievement exactly once, and to show
a streak.

Celebrations previously fired only from a live socket event, so one that
arrived while the app was backgrounded was simply lost, and nothing could make
it idempotent across two devices. `gam_user_badges.seen_at` and
`gam_user_stats.celebrated_tier` move that acknowledgement server-side.

`celebrated_tier` is left NULL on backfill rather than seeded with
current_tier. The service treats a first sighting of NULL as "record silently",
so nobody gets a tier-up celebration for a tier they reached months ago -- but
leaving it NULL keeps that decision in one place instead of baking it into a
migration that cannot be revisited.

Streak columns start at 0/NULL. The first daily_login after deploy sets a
streak of 1, which is honest: we do not know how many consecutive days anyone
had before we started counting, and inventing one would put a number on screen
that no data supports.
"""

from alembic import op
import sqlalchemy as sa

revision = "e1a7c93b5d20"
down_revision = "49bdc993a1eb"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("gam_user_badges", sa.Column("seen_at", sa.DateTime(), nullable=True))
    # Partial-ish: the only query is "unseen for this user", so the index earns
    # its keep on the NULLs rather than the whole column.
    op.create_index(
        "ix_gam_user_badges_seen_at", "gam_user_badges", ["seen_at"], unique=False
    )

    op.add_column(
        "gam_user_stats",
        sa.Column("celebrated_tier", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "gam_user_stats",
        sa.Column("streak_days", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "gam_user_stats",
        sa.Column("longest_streak", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "gam_user_stats", sa.Column("last_active_date", sa.Date(), nullable=True)
    )

    # server_default was only needed to backfill existing rows without a table
    # rewrite; the model owns the default from here.
    op.alter_column("gam_user_stats", "streak_days", server_default=None)
    op.alter_column("gam_user_stats", "longest_streak", server_default=None)


def downgrade():
    op.drop_column("gam_user_stats", "last_active_date")
    op.drop_column("gam_user_stats", "longest_streak")
    op.drop_column("gam_user_stats", "streak_days")
    op.drop_column("gam_user_stats", "celebrated_tier")
    op.drop_index("ix_gam_user_badges_seen_at", table_name="gam_user_badges")
    op.drop_column("gam_user_badges", "seen_at")
