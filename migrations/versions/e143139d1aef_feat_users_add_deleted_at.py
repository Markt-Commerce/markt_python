"""feat(users): add deleted_at for account deletion

Revision ID: e143139d1aef
Revises: 72bf175405d5
Create Date: 2026-09-01

Marks accounts the user has deleted in-app (Apple App Store 5.1.1(v)).
Nullable, so existing rows are untouched and read as "not deleted".
"""

from alembic import op
import sqlalchemy as sa


revision = "e143139d1aef"
down_revision = "72bf175405d5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])


def downgrade():
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_column("users", "deleted_at")
