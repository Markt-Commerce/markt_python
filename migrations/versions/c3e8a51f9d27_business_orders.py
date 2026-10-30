"""feat(business): mark business orders

Revision ID: c3e8a51f9d27
Revises: b7d2e94c1a58
Create Date: 2026-10-30

**orders.is_business**: true when the buyer was a Markt Business account at
the moment the order was placed (app.business.orders.stamp_business_order).
Stamped rather than derived, so a lapsed subscription later does not rewrite
order history. Server default false, so every existing order reads as the
consumer order it was.

The partial index serves the business order lists (`?is_business=true`),
which select a small slice of a large table.
"""

from alembic import op
import sqlalchemy as sa

revision = "c3e8a51f9d27"
down_revision = "b7d2e94c1a58"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "orders",
        sa.Column("is_business", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_orders_is_business",
        "orders",
        ["is_business"],
        postgresql_where=sa.text("is_business"),
    )


def downgrade():
    op.drop_index("ix_orders_is_business", table_name="orders")
    op.drop_column("orders", "is_business")
