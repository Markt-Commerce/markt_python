"""Phase 3: wallet top-ups, order returns, seller subaccounts.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    return column in {
        col["name"] for col in inspect(op.get_bind()).get_columns(table)
    }


def upgrade():
    op.execute(
        "ALTER TYPE walletreferencetype "
        "ADD VALUE IF NOT EXISTS 'WALLET_TOPUP'"
    )

    if not _column_exists("orders", "paystack_split_used"):
        op.add_column(
            "orders",
            sa.Column(
                "paystack_split_used",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    seller_columns = {
        col["name"] for col in inspect(op.get_bind()).get_columns("sellers")
    }
    if "paystack_subaccount_code" not in seller_columns:
        op.add_column(
            "sellers",
            sa.Column("paystack_subaccount_code", sa.String(length=50), nullable=True),
        )
    if "payout_bank_code" not in seller_columns:
        op.add_column(
            "sellers",
            sa.Column("payout_bank_code", sa.String(length=10), nullable=True),
        )
    if "payout_account_number" not in seller_columns:
        op.add_column(
            "sellers",
            sa.Column("payout_account_number", sa.String(length=20), nullable=True),
        )
    if "payout_account_name" not in seller_columns:
        op.add_column(
            "sellers",
            sa.Column("payout_account_name", sa.String(length=100), nullable=True),
        )

    bind = op.get_bind()

    order_return_status = postgresql.ENUM(
        "REQUESTED",
        "APPROVED",
        "REJECTED",
        "REFUNDED",
        name="orderreturnstatus",
        create_type=False,
    )
    topup_status = postgresql.ENUM(
        "PENDING",
        "COMPLETED",
        "FAILED",
        name="topupstatus",
        create_type=False,
    )
    order_return_status.create(bind, checkfirst=True)
    topup_status.create(bind, checkfirst=True)

    if not _table_exists("order_returns"):
        op.create_table(
            "order_returns",
            sa.Column("id", sa.String(length=12), nullable=False),
            sa.Column("order_id", sa.String(length=12), nullable=False),
            sa.Column("buyer_id", sa.Integer(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", order_return_status, nullable=False),
            sa.Column("refund_amount", sa.Float(), nullable=True),
            sa.Column("seller_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["buyer_id"], ["buyers.id"]),
            sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _table_exists("wallet_topups"):
        op.create_table(
            "wallet_topups",
            sa.Column("id", sa.String(length=12), nullable=False),
            sa.Column("user_id", sa.String(length=12), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("status", topup_status, nullable=False),
            sa.Column("paystack_reference", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("paystack_reference"),
        )


def downgrade():
    op.drop_table("wallet_topups")
    op.drop_table("order_returns")
    op.drop_column("sellers", "payout_account_name")
    op.drop_column("sellers", "payout_account_number")
    op.drop_column("sellers", "payout_bank_code")
    op.drop_column("sellers", "paystack_subaccount_code")
    op.drop_column("orders", "paystack_split_used")
    op.execute("DROP TYPE IF EXISTS topupstatus")
    op.execute("DROP TYPE IF EXISTS orderreturnstatus")
