"""delivery serviceability and quotes

Adds the layer that answers "can we deliver this, and for how much" before a
buyer pays. See docs/ADR-001-delivery-quoting.md.

Sits above Market/Area rather than replacing them: those stay membership
concepts, explicitly assigned. No data is seeded here -- served cities, zones
and lanes are business decisions, and an empty registry correctly means "we
deliver nowhere yet" rather than silently serving everywhere.

Revision ID: e4b1a9c73d25
Revises: c7a2e5d81f43
Create Date: 2026-09-12
"""

from alembic import op
import sqlalchemy as sa


revision = "e4b1a9c73d25"
down_revision = "c7a2e5d81f43"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "service_cities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("slug", sa.String(length=110), nullable=False, unique=True),
        # Defaults to False: launching a city is a deliberate act.
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("launched_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "service_zones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "city_id",
            sa.Integer(),
            sa.ForeignKey("service_cities.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=110), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("centroid_lat", sa.Float(), nullable=False),
        sa.Column("centroid_lng", sa.Float(), nullable=False),
        sa.Column("radius_km", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_service_zones_city_active", "service_zones", ["city_id", "is_active"]
    )

    op.create_table(
        "delivery_lanes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "from_zone_id", sa.Integer(), sa.ForeignKey("service_zones.id"), nullable=False
        ),
        sa.Column(
            "to_zone_id", sa.Integer(), sa.ForeignKey("service_zones.id"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("base_fee_minor_override", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("from_zone_id", "to_zone_id", name="uq_lane_from_to"),
    )
    op.create_index("ix_delivery_lanes_active", "delivery_lanes", ["is_active"])

    op.create_table(
        "delivery_quotes",
        sa.Column("id", sa.String(length=12), primary_key=True),
        sa.Column("buyer_id", sa.Integer(), sa.ForeignKey("buyers.id"), nullable=False),
        sa.Column("seller_id", sa.Integer(), sa.ForeignKey("sellers.id"), nullable=True),
        sa.Column(
            "pickup_zone_id", sa.Integer(), sa.ForeignKey("service_zones.id"), nullable=False
        ),
        sa.Column(
            "dropoff_zone_id", sa.Integer(), sa.ForeignKey("service_zones.id"), nullable=False
        ),
        sa.Column("pickup_lat", sa.Float(), nullable=False),
        sa.Column("pickup_lng", sa.Float(), nullable=False),
        sa.Column("dropoff_lat", sa.Float(), nullable=False),
        sa.Column("dropoff_lng", sa.Float(), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=False),
        sa.Column("strategy", sa.String(length=50), nullable=False),
        sa.Column("strategy_version", sa.String(length=20), nullable=False),
        # Integer kobo, not Numeric: a quote gets divided by a participant
        # count in batch, and integer minor units are the only way that
        # division is auditable to the kobo.
        sa.Column("fee_minor", sa.Integer(), nullable=False),
        sa.Column("breakdown", sa.JSON(), nullable=False),
        sa.Column(
            "precision", sa.String(length=20), nullable=False, server_default="approximate"
        ),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "CONSUMED", "EXPIRED", name="quotestatus"),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("order_id", sa.String(length=12), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_delivery_quotes_buyer_status", "delivery_quotes", ["buyer_id", "status"]
    )


def downgrade():
    op.drop_index("ix_delivery_quotes_buyer_status", table_name="delivery_quotes")
    op.drop_table("delivery_quotes")
    op.execute("DROP TYPE IF EXISTS quotestatus")
    op.drop_index("ix_delivery_lanes_active", table_name="delivery_lanes")
    op.drop_table("delivery_lanes")
    op.drop_index("ix_service_zones_city_active", table_name="service_zones")
    op.drop_table("service_zones")
    op.drop_table("service_cities")
