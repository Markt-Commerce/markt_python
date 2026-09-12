"""niche avatar and banner

Revision ID: 49bdc993a1eb
Revises: b2e7c91a4d38
Create Date: 2026-09-04

A community reads as a place because it has a face. Niches had no imagery at
all, so every one of them rendered as an initial on a coloured square -- fine
for a list, hopeless for the card-and-banner layout the communities UI needs.

The constraints are named explicitly. Autogenerate emits
create_foreign_key(None, ...) / drop_constraint(None, ...), which works on the
way up and then fails on the way down with

    CompileError: Can't emit DROP CONSTRAINT for constraint
    ForeignKeyConstraint(...); it has no name

That is exactly the defect that already makes `flask db downgrade base`
unrunnable on this project (an unnamed FK on shipping_addresses in the v3.0
schema). Not repeating it here.
"""

from alembic import op
import sqlalchemy as sa


revision = "49bdc993a1eb"
down_revision = "b2e7c91a4d38"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("niches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("image_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("banner_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_niches_image_id_media", "media", ["image_id"], ["id"]
        )
        batch_op.create_foreign_key(
            "fk_niches_banner_id_media", "media", ["banner_id"], ["id"]
        )


def downgrade():
    with op.batch_alter_table("niches", schema=None) as batch_op:
        batch_op.drop_constraint("fk_niches_banner_id_media", type_="foreignkey")
        batch_op.drop_constraint("fk_niches_image_id_media", type_="foreignkey")
        batch_op.drop_column("banner_id")
        batch_op.drop_column("image_id")
