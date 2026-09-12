"""saved address city and state

Autogenerate again swept in alter_column operations on created_at/updated_at
across a dozen unrelated tables -- the same pre-existing model/schema drift
noted in 3f1d5a85ff68, nothing to do with this change. Removed: this
migration adds two nullable columns to one table and nothing else.

Revision ID: c182c673b6c4
Revises: 3f1d5a85ff68

"""
from alembic import op
import sqlalchemy as sa

revision = "c182c673b6c4"
down_revision = "3f1d5a85ff68"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "saved_addresses", sa.Column("city", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "saved_addresses", sa.Column("state", sa.String(length=100), nullable=True)
    )


def downgrade():
    op.drop_column("saved_addresses", "state")
    op.drop_column("saved_addresses", "city")
