"""feat(business): Markt Business foundation

Revision ID: b7d2e94c1a58
Revises: e9f4a1b2c3d4
Create Date: 2026-10-28

A business is an ordinary user carrying the **users.is_business** tag; its
buyer and seller accounts are the manufacturer and producer sides. Everything
here is additive and every new column on an existing table is nullable or has
a server default, so consumer rows and code paths are untouched.

- **business_profiles**: the details behind the tag, one per user.
- **business_listings**: B2B terms for a product, one per product, as a side
  table so consumer listings carry none of it.
- **buyer_requests** / **seller_offers**: procurement fields. A procurement
  request is a buyer request from a business account, not a new table.
- **business_subscription_plans / _features / business_subscriptions**: ready
  for when BUSINESS_SUBSCRIPTIONS_ENABLED is turned on. No plans are seeded.

Enums are created by name (businessverificationstatus,
businesssubscriptionstatus) and dropped on downgrade.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b7d2e94c1a58"
down_revision = "e9f4a1b2c3d4"
branch_labels = None
depends_on = None


verification_status = postgresql.ENUM(
    "UNVERIFIED",
    "PENDING",
    "VERIFIED",
    "REJECTED",
    name="businessverificationstatus",
    create_type=False,
)
subscription_status = postgresql.ENUM(
    "PENDING",
    "ACTIVE",
    "CANCELLED",
    "EXPIRED",
    name="businesssubscriptionstatus",
    create_type=False,
)


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade():
    bind = op.get_bind()
    verification_status.create(bind, checkfirst=True)
    subscription_status.create(bind, checkfirst=True)

    op.add_column(
        "users",
        sa.Column("is_business", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.create_table(
        "business_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=12), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "business_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("industry", sa.String(length=50), nullable=True),
        sa.Column("contact_email", sa.String(length=120), nullable=True),
        sa.Column("contact_phone", sa.String(length=20), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("cover_image_url", sa.String(length=500), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("registration_number", sa.String(length=50), nullable=True),
        sa.Column(
            "verification_status",
            verification_status,
            nullable=False,
            server_default="UNVERIFIED",
        ),
        sa.Column("verification_note", sa.String(length=500), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_business_profile_user"),
    )
    op.create_index("ix_business_profiles_city", "business_profiles", ["city"])
    op.create_index("ix_business_profiles_state", "business_profiles", ["state"])

    op.create_table(
        "business_listings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(length=12), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("available_quantity", sa.Numeric(14, 3), nullable=True),
        sa.Column("min_order_quantity", sa.Numeric(14, 3), nullable=True),
        sa.Column(
            "price_negotiable", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("production_capacity", sa.String(length=150), nullable=True),
        sa.Column("availability", sa.String(length=150), nullable=True),
        sa.Column(
            "specifications", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=100), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_business_listing_product"),
    )
    op.create_index("ix_business_listings_city", "business_listings", ["city"])
    op.create_index("ix_business_listings_state", "business_listings", ["state"])

    op.create_table(
        "business_subscription_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="NGN"
        ),
        sa.Column(
            "billing_interval",
            sa.String(length=20),
            nullable=False,
            server_default="monthly",
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )

    op.create_table(
        "business_subscription_features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("feature_key", sa.String(length=50), nullable=False),
        sa.Column("limit_value", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["business_subscription_plans.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "feature_key", name="uq_plan_feature"),
    )

    op.create_table(
        "business_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=12), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column(
            "status", subscription_status, nullable=False, server_default="PENDING"
        ),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("renewal_date", sa.DateTime(), nullable=True),
        sa.Column("payment_reference", sa.String(length=100), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["business_subscription_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_reference"),
    )
    op.create_index(
        "ix_business_subscriptions_user_id", "business_subscriptions", ["user_id"]
    )

    op.add_column(
        "buyer_requests",
        sa.Column("is_business", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("buyer_requests", sa.Column("quantity", sa.Numeric(14, 3)))
    op.add_column("buyer_requests", sa.Column("unit", sa.String(length=20)))
    op.add_column(
        "buyer_requests",
        sa.Column("specifications", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column(
        "buyer_requests", sa.Column("delivery_location", sa.String(length=255))
    )
    op.add_column("buyer_requests", sa.Column("required_delivery_date", sa.Date()))
    op.create_index(
        "ix_buyer_requests_is_business",
        "buyer_requests",
        ["is_business"],
        postgresql_where=sa.text("is_business"),
    )

    op.add_column("seller_offers", sa.Column("proposed_quantity", sa.Numeric(14, 3)))


def downgrade():
    op.drop_column("seller_offers", "proposed_quantity")

    op.drop_index("ix_buyer_requests_is_business", table_name="buyer_requests")
    for column in (
        "required_delivery_date",
        "delivery_location",
        "specifications",
        "unit",
        "quantity",
        "is_business",
    ):
        op.drop_column("buyer_requests", column)

    op.drop_index(
        "ix_business_subscriptions_user_id", table_name="business_subscriptions"
    )
    op.drop_table("business_subscriptions")
    op.drop_table("business_subscription_features")
    op.drop_table("business_subscription_plans")
    op.drop_index("ix_business_listings_state", table_name="business_listings")
    op.drop_index("ix_business_listings_city", table_name="business_listings")
    op.drop_table("business_listings")
    op.drop_index("ix_business_profiles_state", table_name="business_profiles")
    op.drop_index("ix_business_profiles_city", table_name="business_profiles")
    op.drop_table("business_profiles")

    op.drop_column("users", "is_business")

    bind = op.get_bind()
    subscription_status.drop(bind, checkfirst=True)
    verification_status.drop(bind, checkfirst=True)
