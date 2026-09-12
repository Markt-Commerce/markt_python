"""order delivery state and quote snapshot

The delivery half of an order: a snapshot of the quote that priced it, the
state machine the buyer sees, and the batch fields (opt-in, run, solo ceiling,
settled amount).

A separate table rather than columns on orders, because delivery has its own
lifecycle that outlives payment -- an order can be cancelled while its parcel
is mid-flight, and neither state machine should have to know the other's
terminal states.

Revision ID: f5c2d8a16b34
Revises: e4b1a9c73d25
Create Date: 2026-09-12
"""

from alembic import op
import sqlalchemy as sa


revision = "f5c2d8a16b34"
down_revision = "e4b1a9c73d25"
branch_labels = None
depends_on = None

DELIVERY_STATES = (
    "QUOTED",
    "PAID",
    "AWAITING_DISPATCH",
    "JOB_CREATED",
    "ASSIGNED",
    "PICKED_UP",
    "IN_TRANSIT",
    "DELIVERED",
    "FAILED",
    "CANCELLED",
)


def upgrade():
    op.create_table(
        "order_deliveries",
        sa.Column("id", sa.String(length=12), primary_key=True),
        sa.Column(
            "order_id",
            sa.String(length=12),
            sa.ForeignKey("orders.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "quote_id",
            sa.String(length=12),
            sa.ForeignKey("delivery_quotes.id"),
            nullable=True,
        ),
        sa.Column(
            "state",
            sa.Enum(*DELIVERY_STATES, name="deliverystate"),
            nullable=False,
            server_default="QUOTED",
        ),
        # Quote snapshot. Kept in full rather than joined to delivery_quotes:
        # quotes are prunable and strategies get replaced, and a fee somebody
        # paid has to stay explainable for as long as the order exists.
        sa.Column("fee_minor", sa.Integer(), nullable=False),
        sa.Column("breakdown", sa.JSON(), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("strategy", sa.String(length=50), nullable=True),
        sa.Column("strategy_version", sa.String(length=20), nullable=True),
        sa.Column("pickup_lat", sa.Float(), nullable=True),
        sa.Column("pickup_lng", sa.Float(), nullable=True),
        sa.Column("dropoff_lat", sa.Float(), nullable=True),
        sa.Column("dropoff_lng", sa.Float(), nullable=True),
        # Batch is opt-in, so this defaults to false and nothing joins a run
        # without being asked.
        sa.Column(
            "batch_opt_in", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "delivery_run_id",
            sa.String(length=12),
            sa.ForeignKey("delivery_runs.id"),
            nullable=True,
        ),
        sa.Column("solo_fee_minor", sa.Integer(), nullable=False),
        sa.Column("settled_fee_minor", sa.Integer(), nullable=True),
        sa.Column("external_job_id", sa.String(length=100), nullable=True),
        sa.Column("last_status_at", sa.DateTime(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_order_deliveries_state", "order_deliveries", ["state"])
    op.create_index(
        "ix_order_deliveries_run", "order_deliveries", ["delivery_run_id"]
    )


def downgrade():
    op.drop_index("ix_order_deliveries_run", table_name="order_deliveries")
    op.drop_index("ix_order_deliveries_state", table_name="order_deliveries")
    op.drop_table("order_deliveries")
    op.execute("DROP TYPE IF EXISTS deliverystate")
