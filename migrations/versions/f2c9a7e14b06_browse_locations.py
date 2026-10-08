"""feat(location): browse locations, and an index for proximity queries

Revision ID: f2c9a7e14b06
Revises: c8e4b1f7a903
Create Date: 2026-09-10

Two things.

**browse_locations** stores where someone is *looking*, which is deliberately
not where they want things sent. Keyed by user id or a guest device id -- never
both -- so a guest can choose an area before creating an account and keep it
afterwards.

**The composite index on sellers(shop_latitude, shop_longitude)** is what makes
the bounding-box prefilter index-only. Without it, every proximity query is a
sequential scan of the seller table, which is fine at three sellers and not at
three thousand. PostGIS is not installed here, so this is a plain B-tree over
the two float columns rather than a GIST index over a geography type; if
production has the extension, that swap is additive and does not change the
query shape (see app/libs/geo.py).

Partial on NOT NULL: a seller with no shop location cannot satisfy a bounding
box, so indexing those rows would only make the index bigger.
"""

from alembic import op
import sqlalchemy as sa

revision = "f2c9a7e14b06"
down_revision = "c8e4b1f7a903"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "browse_locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=12), nullable=True),
        sa.Column("guest_id", sa.String(length=64), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=True),
        sa.Column("state", sa.String(length=80), nullable=True),
        sa.Column("lga", sa.String(length=80), nullable=True),
        sa.Column(
            "updated_at_utc",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_browse_location_user"),
        sa.UniqueConstraint("guest_id", name="uq_browse_location_guest"),
    )
    op.create_index(
        "ix_browse_locations_guest_id", "browse_locations", ["guest_id"], unique=False
    )

    op.create_index(
        "ix_sellers_shop_coords",
        "sellers",
        ["shop_latitude", "shop_longitude"],
        unique=False,
        postgresql_where=sa.text("shop_latitude IS NOT NULL"),
    )


def downgrade():
    op.drop_index("ix_sellers_shop_coords", table_name="sellers")
    op.drop_index("ix_browse_locations_guest_id", table_name="browse_locations")
    op.drop_table("browse_locations")
