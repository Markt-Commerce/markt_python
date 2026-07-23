"""Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-06-25 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    return column in {
        col["name"] for col in inspect(op.get_bind()).get_columns(table)
    }


def upgrade():
    if not _column_exists("orders", "cancelled_at"):
        op.add_column("orders", sa.Column("cancelled_at", sa.DateTime(), nullable=True))
    if not _column_exists("orders", "cancel_reason"):
        op.add_column("orders", sa.Column("cancel_reason", sa.Text(), nullable=True))

    bind = op.get_bind()

    wallet_entry_type = postgresql.ENUM(
        "CREDIT", "DEBIT", name="walletentrytype", create_type=False
    )
    wallet_reference_type = postgresql.ENUM(
        "ORDER_SETTLEMENT",
        "ORDER_REFUND",
        "WITHDRAWAL",
        "ADJUSTMENT",
        name="walletreferencetype",
        create_type=False,
    )
    withdrawal_status = postgresql.ENUM(
        "PENDING",
        "PROCESSING",
        "COMPLETED",
        "FAILED",
        name="withdrawalstatus",
        create_type=False,
    )

    wallet_entry_type.create(bind, checkfirst=True)
    wallet_reference_type.create(bind, checkfirst=True)
    withdrawal_status.create(bind, checkfirst=True)

    if not _table_exists("wallet_accounts"):
        op.create_table(
            "wallet_accounts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.String(length=12), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("available_balance", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "currency", name="uq_wallet_user_currency"),
        )

    if not _table_exists("wallet_entries"):
        op.create_table(
            "wallet_entries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("wallet_account_id", sa.Integer(), nullable=False),
            sa.Column("entry_type", wallet_entry_type, nullable=False),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("balance_after", sa.Float(), nullable=False),
            sa.Column("reference_type", wallet_reference_type, nullable=False),
            sa.Column("reference_id", sa.String(length=50), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("idempotency_key", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["wallet_account_id"], ["wallet_accounts.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key"),
        )

    if not _table_exists("withdrawal_requests"):
        op.create_table(
            "withdrawal_requests",
            sa.Column("id", sa.String(length=12), nullable=False),
            sa.Column("user_id", sa.String(length=12), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("bank_code", sa.String(length=10), nullable=False),
            sa.Column("account_number", sa.String(length=20), nullable=False),
            sa.Column("account_name", sa.String(length=100), nullable=False),
            sa.Column("status", withdrawal_status, nullable=False),
            sa.Column("paystack_transfer_ref", sa.String(length=100), nullable=True),
            sa.Column("failure_reason", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    op.drop_table("withdrawal_requests")
    op.drop_table("wallet_entries")
    op.drop_table("wallet_accounts")
    op.drop_column("orders", "cancel_reason")
    op.drop_column("orders", "cancelled_at")
    op.execute("DROP TYPE IF EXISTS withdrawalstatus")
    op.execute("DROP TYPE IF EXISTS walletreferencetype")
    op.execute("DROP TYPE IF EXISTS walletentrytype")
