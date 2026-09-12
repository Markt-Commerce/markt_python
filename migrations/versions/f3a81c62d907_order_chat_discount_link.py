"""which chat offer an order used

Needed to spend a discount when the order is paid instead of when it is
created. Nothing recorded the link, so at payment time there was no way to
know which offer to spend.

Nullable, no backfill: orders that predate this either used no offer or
already spent one at checkout.

Revision ID: f3a81c62d907
Revises: e7b3c9d21f84
Create Date: 2026-09-12
"""

from alembic import op
import sqlalchemy as sa


revision = "f3a81c62d907"
down_revision = "e7b3c9d21f84"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("chat_discount_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_orders_chat_discount_id",
        "orders",
        "chat_discounts",
        ["chat_discount_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint("fk_orders_chat_discount_id", "orders", type_="foreignkey")
    op.drop_column("orders", "chat_discount_id")
