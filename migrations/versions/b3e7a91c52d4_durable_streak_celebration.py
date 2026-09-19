"""durable streak celebration

The streak event is emitted inside the login request, before the app has a
user id and therefore before it has connected its gamification socket -- so
the celebration was always lost on sign-in, the one occasion it exists for.
Badges and tiers already survive this because the server records what it has
acknowledged; this gives the streak the same.

Nullable with no backfill: NULL means "never celebrated", and the service
records a first sighting silently rather than firing at every mid-streak user
on deploy. Same rule as celebrated_tier, for the same reason.

Revision ID: b3e7a91c52d4
Revises: a1c6f28d4b90
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa


revision = "b3e7a91c52d4"
down_revision = "a1c6f28d4b90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "gam_user_stats", sa.Column("celebrated_streak", sa.Integer(), nullable=True)
    )


def downgrade():
    op.drop_column("gam_user_stats", "celebrated_streak")
