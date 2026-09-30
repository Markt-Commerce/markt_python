"""Seller admin fields (verification note, featured)

§2 seller verification & shop (docs/ADMIN_MILESTONE_1_PLAN.md, Increment 3):

- sellers.verification_note -- the current admin reason behind
  verification_status (verify/reject note). Full history is in
  admin_audit_logs; this is the denormalised current reason.
- sellers.is_featured -- editorial promotion, distinct from verification
  (trust) and is_active (can-sell). NOT NULL default false; existing rows
  backfill to false via server_default.

Revision ID: d8a6c4f13e29
Revises: c7f5a3e21b48
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "d8a6c4f13e29"
down_revision = "c7f5a3e21b48"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sellers", sa.Column("verification_note", sa.String(length=500), nullable=True)
    )
    op.add_column(
        "sellers",
        sa.Column(
            "is_featured",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Drop the server_default now that existing rows are backfilled: the model
    # supplies the default in Python, matching how other boolean flags here are
    # declared (no DB-level default).
    op.alter_column("sellers", "is_featured", server_default=None)


def downgrade():
    op.drop_column("sellers", "is_featured")
    op.drop_column("sellers", "verification_note")
