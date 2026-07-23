"""Add ORDER_PAYMENT to walletreferencetype enum.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
"""

from alembic import op

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE walletreferencetype "
        "ADD VALUE IF NOT EXISTS 'ORDER_PAYMENT'"
    )


def downgrade():
    pass
