"""what was bought, frozen at the moment of buying

order_items.price has always been a snapshot. The name and the photo were
not -- they were read live off the product, so a seller editing a listing
after a sale changed what the buyer saw in their own order history. Sellers
can now change photos from the app, which is exactly the bait-and-switch this
closes.

Nullable with no backfill: orders placed before this have no snapshot, and the
read path falls back to the live product for them. Backfilling would write
today's name onto a year-old order and call it history.

Revision ID: e7b3c9d21f84
Revises: d4a9b2e73c51
Create Date: 2026-09-12
"""

from alembic import op
import sqlalchemy as sa


revision = "e7b3c9d21f84"
down_revision = "d4a9b2e73c51"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "order_items", sa.Column("product_name", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "order_items",
        sa.Column("product_image_url", sa.String(length=500), nullable=True),
    )


def downgrade():
    op.drop_column("order_items", "product_image_url")
    op.drop_column("order_items", "product_name")
