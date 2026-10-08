"""Admin RBAC and audit log

Foundations for the admin surface (docs/ADMIN_MILESTONE_1_PLAN.md, Increment 1):
- users.admin_role: lightweight staff role. null = not staff. is_admin stays
  the master gate; a super_admin role or is_admin implies every permission
  (app/admin/permissions.py).
- admin_audit_logs: append-only record of staff actions, written in the same
  transaction as the action it describes (app/admin/services.py).

Revision ID: b6e4a2f70c19
Revises: a4f8c2e91d67
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "b6e4a2f70c19"
down_revision = "a4f8c2e91d67"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("admin_role", sa.String(length=32), nullable=True),
    )

    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(length=12), nullable=False),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_audit_logs_actor_id", "admin_audit_logs", ["actor_id"]
    )
    op.create_index("ix_admin_audit_logs_action", "admin_audit_logs", ["action"])
    op.create_index(
        "ix_admin_audit_logs_target_type", "admin_audit_logs", ["target_type"]
    )
    op.create_index(
        "ix_admin_audit_logs_target_id", "admin_audit_logs", ["target_id"]
    )
    op.create_index(
        "ix_admin_audit_target", "admin_audit_logs", ["target_type", "target_id"]
    )
    op.create_index(
        "ix_admin_audit_actor_created",
        "admin_audit_logs",
        ["actor_id", "created_at"],
    )


def downgrade():
    op.drop_index("ix_admin_audit_actor_created", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_target", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_target_id", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_target_type", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_action", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_actor_id", table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")

    op.drop_column("users", "admin_role")
