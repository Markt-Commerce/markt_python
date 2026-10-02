"""Join the delivery and admin migration branches.

Both feature branches were created from the same parent and later merged
independently.  This revision is deliberately structural: it changes no
schema and only gives Alembic one unambiguous ``head`` for deployments.

Revision ID: e9f4a1b2c3d4
Revises: d7b3c48e19f2, d8a6c4f13e29
Create Date: 2026-10-02
"""

revision = "e9f4a1b2c3d4"
down_revision = ("d7b3c48e19f2", "d8a6c4f13e29")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
