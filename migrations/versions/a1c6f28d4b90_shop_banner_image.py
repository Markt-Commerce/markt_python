"""shop banner image

A shop card needs a wide image behind the avatar; sellers had nowhere to put
one. Nullable with no backfill: an existing shop simply has no banner yet, and
the card falls back to a tinted block rather than a broken image.

Revision ID: a1c6f28d4b90
Revises: 17f4cd9b003f
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa


revision = "a1c6f28d4b90"
down_revision = "17f4cd9b003f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sellers", sa.Column("banner_url", sa.String(length=500), nullable=True)
    )


def downgrade():
    op.drop_column("sellers", "banner_url")
