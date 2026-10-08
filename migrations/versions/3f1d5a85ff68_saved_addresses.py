"""saved addresses

Autogenerate also picked up alter_column operations on created_at/updated_at
across a dozen unrelated tables -- pre-existing drift between the models and
the live schema, nothing to do with this change. They have been removed:
this migration creates one table and nothing else, so it cannot alter a table
it was never meant to touch. The drift is real and worth fixing, but in a
migration that says that is what it is doing.

Revision ID: 3f1d5a85ff68
Revises: f5c2d8a16b34
Create Date: 2026-09-12 13:20:30.477189

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3f1d5a85ff68"
down_revision = "f5c2d8a16b34"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saved_addresses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=12), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=True),
        sa.Column("formatted_address", sa.String(length=500), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column(
            "building_type",
            sa.Enum(
                "HOUSE",
                "APARTMENT",
                "OFFICE",
                "SHOP",
                "HOSTEL",
                "SCHOOL",
                "HOSPITAL",
                "OTHER",
                name="buildingtype",
            ),
            nullable=False,
        ),
        sa.Column("entry_code", sa.String(length=40), nullable=True),
        sa.Column("directions", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.String(length=100), nullable=True),
        sa.Column("contact_phone", sa.String(length=20), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_saved_addresses_user_id"),
        "saved_addresses",
        ["user_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_saved_addresses_user_id"), table_name="saved_addresses")
    op.drop_table("saved_addresses")
    # The enum type is created implicitly by create_table above and has to be
    # dropped explicitly, or re-running the upgrade fails on a type that
    # already exists.
    sa.Enum(name="buildingtype").drop(op.get_bind(), checkfirst=True)
