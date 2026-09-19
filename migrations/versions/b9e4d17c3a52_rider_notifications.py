"""Notifications and push tokens for delivery partners

A rider could not be notified at all. Notification.user_id and
PushToken.user_id both reference `users`, and a DeliveryUser lives in
`delivery_users` with a DEL_ id -- so the row was refused by the foreign key,
and because every notification call site wraps itself in `except Exception`,
nothing ever said so. The rider app had nowhere to send a push token even
once it asked for one.

Same shape as the delivery-partner wallet migration (a4f8c2e91d67): a second
nullable FK per table and a check constraint requiring exactly one owner.

Revision ID: b9e4d17c3a52
Revises: a4f8c2e91d67
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa


revision = "b9e4d17c3a52"
down_revision = "a4f8c2e91d67"
branch_labels = None
depends_on = None

NEW_TYPES = (
    "DELIVERY_AVAILABLE",
    "DELIVERY_ASSIGNED",
    "DELIVERY_EARNING_CREDITED",
)


def upgrade():
    for label in NEW_TYPES:
        op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{label}'")

    for table in ("notifications", "push_tokens"):
        op.alter_column(table, "user_id", nullable=True)
        op.add_column(
            table,
            sa.Column("delivery_user_id", sa.String(length=12), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{table}_delivery_user_id",
            table,
            "delivery_users",
            ["delivery_user_id"],
            ["id"],
        )
        op.create_index(f"ix_{table}_delivery_user_id", table, ["delivery_user_id"])
        op.create_check_constraint(
            f"ck_{table}_single_owner",
            table,
            "(user_id IS NOT NULL) <> (delivery_user_id IS NOT NULL)",
        )


def downgrade():
    for table in ("notifications", "push_tokens"):
        op.drop_constraint(f"ck_{table}_single_owner", table, type_="check")
        op.drop_index(f"ix_{table}_delivery_user_id", table_name=table)
        op.drop_constraint(f"fk_{table}_delivery_user_id", table, type_="foreignkey")
        op.drop_column(table, "delivery_user_id")
        op.alter_column(table, "user_id", nullable=False)
