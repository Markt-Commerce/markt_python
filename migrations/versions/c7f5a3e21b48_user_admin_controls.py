"""User admin controls (suspend / ban / force-logout)

§1 user management (docs/ADMIN_MILESTONE_1_PLAN.md, Increment 2). Adds the
account-control state the admin surface acts on, kept separate from the user's
own is_active/deactivated_at (self-deactivation) and deleted_at (self-deletion):

- suspended_at / suspension_reason -- reversible admin hold.
- banned_at / ban_reason           -- reversible admin removal.
- tokens_valid_from                -- force-logout epoch; bearer tokens issued
  before it are rejected (main.setup request loader).

All nullable, so existing rows need no backfill.

Revision ID: c7f5a3e21b48
Revises: b6e4a2f70c19
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "c7f5a3e21b48"
down_revision = "b6e4a2f70c19"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("suspended_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users", sa.Column("suspension_reason", sa.String(length=255), nullable=True)
    )
    op.add_column("users", sa.Column("banned_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users", sa.Column("ban_reason", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "users", sa.Column("tokens_valid_from", sa.DateTime(), nullable=True)
    )
    op.create_index("ix_users_suspended_at", "users", ["suspended_at"])
    op.create_index("ix_users_banned_at", "users", ["banned_at"])


def downgrade():
    op.drop_index("ix_users_banned_at", table_name="users")
    op.drop_index("ix_users_suspended_at", table_name="users")
    op.drop_column("users", "tokens_valid_from")
    op.drop_column("users", "ban_reason")
    op.drop_column("users", "banned_at")
    op.drop_column("users", "suspension_reason")
    op.drop_column("users", "suspended_at")
