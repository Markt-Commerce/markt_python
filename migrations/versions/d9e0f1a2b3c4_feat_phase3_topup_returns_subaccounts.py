"""Phase 3: wallet top-ups, order returns, seller subaccounts.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
"""

from alembic import op
import sqlalchemy as sa


revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE walletreferencetype "
        "ADD VALUE IF NOT EXISTS 'WALLET_TOPUP'"
    )

    op.add_column(
        "orders",
        sa.Column(
            "paystack_split_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "sellers",
        sa.Column("paystack_subaccount_code", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "sellers",
        sa.Column("payout_bank_code", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "sellers",
        sa.Column("payout_account_number", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "sellers",
        sa.Column("payout_account_name", sa.String(length=100), nullable=True),
    )

    order_return_status = sa.Enum(
        "REQUESTED",
        "APPROVED",
        "REJECTED",
        "REFUNDED",
        name="orderreturnstatus",
    )
    topup_status = sa.Enum(
        "PENDING",
        "COMPLETED",
        "FAILED",
        name="topupstatus",
    )
    order_return_status.create(op.get_bind(), checkfirst=True)
    topup_status.create(op.get_bind(), checkfirst=True)

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
