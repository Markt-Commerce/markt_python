"""Rider offer holds.

Two new assignment statuses and the expiry that drives them:

  OFFERED  -- a rider has this order held while they decide
  EXPIRED  -- the hold ran out with nobody acting on it

`expires_at` carries both the end of a live hold and the end of the cooldown
after a decline or a lapse. See app/deliveries/offers.py for why a decline
is now temporary: it used to be permanent, and a handful of declines could
make an order invisible to every rider near it with nothing to put it back.

Revision ID: c7f31a90b4de
Revises: 78718855a3f6
Create Date: 2026-09-19

"""

import sqlalchemy as sa
from alembic import op

revision = "c7f31a90b4de"
down_revision = "78718855a3f6"
branch_labels = None
depends_on = None


def upgrade():
    # Native Postgres enums cannot gain a value inside a transaction that
    # then uses it, and ADD VALUE is not transactional at all -- so these go
    # first, on their own, exactly as FAILED was added in 72bf175405d5.
    op.execute("ALTER TYPE assignmentstatus ADD VALUE IF NOT EXISTS 'OFFERED'")
    op.execute("ALTER TYPE assignmentstatus ADD VALUE IF NOT EXISTS 'EXPIRED'")

    op.add_column(
        "delivery_order_assignments",
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_delivery_order_assignments_expires_at",
        "delivery_order_assignments",
        ["expires_at"],
    )


def downgrade():
    op.drop_index(
        "ix_delivery_order_assignments_expires_at",
        table_name="delivery_order_assignments",
    )
    op.drop_column("delivery_order_assignments", "expires_at")
    # The enum labels are deliberately left in place. Postgres cannot drop a
    # value from an enum type, and recreating the type would mean rewriting
    # every row that references it -- a far bigger operation than the column
    # this migration actually added.
