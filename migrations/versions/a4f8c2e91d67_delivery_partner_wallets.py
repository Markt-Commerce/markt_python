"""Delivery partner wallets

Lets a rider's wallet live in the same wallet_accounts/withdrawal_requests
tables buyers/sellers already use, instead of a parallel system --
DeliveryUser is a structurally separate table from User (delivery_users vs
users, DEL_ vs USR_ prefixed ids), so the existing single `user_id` FK
can't reference both. Adds a second nullable `delivery_user_id` FK to each
table and a check constraint requiring exactly one of the two to be set.
WalletEntry needs no change -- it only ever references wallet_account_id.

See REFACTOR_NOTES.md (markt_logistics), "No rider payout functionality"
(2026-09-17, Joshua).

Revision ID: a4f8c2e91d67
Revises: f3a81c62d907
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa


revision = "a4f8c2e91d67"
down_revision = "f3a81c62d907"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE walletreferencetype "
        "ADD VALUE IF NOT EXISTS 'DELIVERY_EARNING'"
    )

    op.alter_column("wallet_accounts", "user_id", nullable=True)
    op.add_column(
        "wallet_accounts",
        sa.Column("delivery_user_id", sa.String(length=12), nullable=True),
    )
    op.create_foreign_key(
        "fk_wallet_accounts_delivery_user_id",
        "wallet_accounts",
        "delivery_users",
        ["delivery_user_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_wallet_delivery_user_currency",
        "wallet_accounts",
        ["delivery_user_id", "currency"],
    )
    op.create_check_constraint(
        "ck_wallet_accounts_single_owner",
        "wallet_accounts",
        "(user_id IS NOT NULL) <> (delivery_user_id IS NOT NULL)",
    )

    op.alter_column("withdrawal_requests", "user_id", nullable=True)
    op.add_column(
        "withdrawal_requests",
        sa.Column("delivery_user_id", sa.String(length=12), nullable=True),
    )
    op.create_foreign_key(
        "fk_withdrawal_requests_delivery_user_id",
        "withdrawal_requests",
        "delivery_users",
        ["delivery_user_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_withdrawal_requests_single_owner",
        "withdrawal_requests",
        "(user_id IS NOT NULL) <> (delivery_user_id IS NOT NULL)",
    )


def downgrade():
    op.drop_constraint(
        "ck_withdrawal_requests_single_owner", "withdrawal_requests", type_="check"
    )
    op.drop_constraint(
        "fk_withdrawal_requests_delivery_user_id",
        "withdrawal_requests",
        type_="foreignkey",
    )
    op.drop_column("withdrawal_requests", "delivery_user_id")
    op.alter_column("withdrawal_requests", "user_id", nullable=False)

    op.drop_constraint(
        "ck_wallet_accounts_single_owner", "wallet_accounts", type_="check"
    )
    op.drop_constraint(
        "uq_wallet_delivery_user_currency", "wallet_accounts", type_="unique"
    )
    op.drop_constraint(
        "fk_wallet_accounts_delivery_user_id", "wallet_accounts", type_="foreignkey"
    )
    op.drop_column("wallet_accounts", "delivery_user_id")
    op.alter_column("wallet_accounts", "user_id", nullable=False)
