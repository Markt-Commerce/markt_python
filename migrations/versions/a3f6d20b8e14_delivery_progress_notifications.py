"""notificationtype labels for rider progress updates

A buyer's order went quiet the moment it was paid for. Everything after
that -- a rider accepting it, reaching the shop, collecting the parcel,
setting off, arriving at the door -- happened with no notification at all,
and the seller was never told a rider was coming for a collection they had
to be present for.

Two labels rather than one: a buyer's "your rider is on the way" and a
seller's "a rider is coming to collect" are different audiences with
different channel policies, and collapsing them would mean one wording for
both.

Alembic's autogenerate does not diff enum labels, so this is hand-written
(same as b2e7c91a4d38, which cleaned up eight labels that went missing
exactly this way).

Revision ID: a3f6d20b8e14
Revises: e2b47c90f1aa
Create Date: 2026-09-20
"""

from alembic import op


revision = "a3f6d20b8e14"
down_revision = "e2b47c90f1aa"
branch_labels = None
depends_on = None

NEW_TYPES = (
    "DELIVERY_STATUS_UPDATE",
    "DELIVERY_PICKUP_UPDATE",
)


def upgrade():
    # IF NOT EXISTS so this is safe to re-run and safe against a database
    # somebody already patched by hand.
    for label in NEW_TYPES:
        op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{label}'")


def downgrade():
    # PostgreSQL cannot drop a value from an enum type, and rebuilding
    # notificationtype to remove two labels would rewrite every notification
    # row to undo an additive change. Deliberate no-op, as in b2e7c91a4d38.
    pass
