"""a delivery failure reason for a run abandoned with the goods aboard

DeliveryFailureReason described three ways a *delivery* fails --
nobody in, bad address, refused. None of them fits a rider who breaks
down halfway through a run while carrying other people's shopping:
nothing is wrong with the order or the buyer, the parcels simply need
collecting from whoever is holding them before anybody can deliver
them.

Without a reason that says so, a run abandoned mid-way created no
failure record at all, so nothing entered the recovery pipeline that
resolve_failure/complete_recovery already provide and the parcels had
no representation anywhere.

Hand-written: alembic's autogenerate does not diff enum labels, which
is the same gap b2e7c91a4d38 cleaned up after.

Revision ID: d7b3c48e19f2
Revises: c8e41b73d92f
Create Date: 2026-09-20
"""

from alembic import op


revision = "d7b3c48e19f2"
down_revision = "c8e41b73d92f"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE deliveryfailurereason ADD VALUE IF NOT EXISTS 'RIDER_UNABLE'"
    )


def downgrade():
    # PostgreSQL cannot remove a value from an enum type, and rebuilding
    # this one to drop a label would rewrite every delivery_failures row
    # to undo an additive change. Deliberate no-op, as in b2e7c91a4d38.
    pass
