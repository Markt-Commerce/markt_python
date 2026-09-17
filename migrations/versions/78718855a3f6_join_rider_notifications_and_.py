"""Join the two notification branches.

Rider notifications (b9e4d17c3a52) and notification preferences
(c1d2e3f4a5b6) were cut from the same revision and merged separately, so
the history had two heads. This is structural: it joins them and changes
no schema.

Revision ID: 78718855a3f6
Revises: b9e4d17c3a52, c1d2e3f4a5b6
Create Date: 2026-09-17 06:38:45.683295

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "78718855a3f6"
down_revision = ("b9e4d17c3a52", "c1d2e3f4a5b6")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
