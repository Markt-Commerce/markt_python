"""Push notification tokens (Expo push).

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _table_exists("push_tokens"):
        op.create_table(
            "push_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(length=12),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column("token", sa.String(length=255), nullable=False, unique=True),
            sa.Column("platform", sa.String(length=20), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index("ix_push_tokens_user_id", "push_tokens", ["user_id"])


def downgrade():
    if _table_exists("push_tokens"):
        op.drop_table("push_tokens")
