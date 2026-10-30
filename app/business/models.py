from enum import Enum

from sqlalchemy.dialects.postgresql import JSONB

from external.database import db
from app.libs.money import MONEY
from app.libs.models import BaseModel


class BusinessVerificationStatus(Enum):
    """Separate from registration on purpose: setting up a business profile
    never makes it verified. Only an admin moves it past UNVERIFIED."""

    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class BusinessProfile(BaseModel):
    """The business details behind a User's is_business tag.

    One per user. The buying and selling sides are the user's existing Buyer
    and Seller accounts, so this holds only what neither of those has: what
    kind of business it is, where it is, and how to reach it.
    """

    __tablename__ = "business_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.String(12),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    # Keys from app.business.constants. Several types are allowed: a food
    # processor buys cassava and sells starch.
    business_types = db.Column(JSONB, nullable=False, default=list)
    industry = db.Column(db.String(50))
    contact_email = db.Column(db.String(120))
    contact_phone = db.Column(db.String(20))
    website = db.Column(db.String(255))
    logo_url = db.Column(db.String(500))
    cover_image_url = db.Column(db.String(500))
    address = db.Column(db.String(255))
    city = db.Column(db.String(100), index=True)
    state = db.Column(db.String(100), index=True)
    country = db.Column(db.String(100), default="Nigeria")
    registration_number = db.Column(db.String(50))
    verification_status = db.Column(
        db.Enum(BusinessVerificationStatus),
        default=BusinessVerificationStatus.UNVERIFIED,
        nullable=False,
    )
    verification_note = db.Column(db.String(500))

    user = db.relationship(
        "User", backref=db.backref("business_profile", uselist=False)
    )


class BusinessListing(BaseModel):
    """B2B details for a Product, one-to-one.

    A side table rather than columns on products so consumer listings carry
    none of it. Quantities are decimal (2.5 tonnes) where Product.stock is an
    integer count; the cart and order path still works in whole units of
    Product, so these figures describe supply, they do not reserve it.
    """

    __tablename__ = "business_listings"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.String(12),
        db.ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    unit = db.Column(db.String(20), nullable=False)
    available_quantity = db.Column(db.Numeric(14, 3))
    min_order_quantity = db.Column(db.Numeric(14, 3))
    # Product.price is the price per unit; this says it is a starting point.
    price_negotiable = db.Column(db.Boolean, default=False, nullable=False)
    production_capacity = db.Column(db.String(150))  # e.g. "20 tonnes per month"
    availability = db.Column(db.String(150))  # e.g. "Year-round", "Oct-Feb"
    specifications = db.Column(JSONB)  # {"moisture": "12%", "grade": "A"}
    city = db.Column(db.String(100), index=True)
    state = db.Column(db.String(100), index=True)

    product = db.relationship(
        "Product", backref=db.backref("business_listing", uselist=False)
    )


class BusinessSubscriptionPlan(BaseModel):
    """A plan an admin defines. None are seeded: prices and benefits are a
    commercial decision that has not been made yet."""

    __tablename__ = "business_subscription_plans"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)  # "starter"
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(MONEY, nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default="NGN")
    billing_interval = db.Column(db.String(20), nullable=False, default="monthly")
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    features = db.relationship(
        "BusinessSubscriptionFeature",
        back_populates="plan",
        cascade="all, delete-orphan",
    )


class BusinessSubscriptionFeature(BaseModel):
    """One entitlement a plan grants, kept apart from the plan so benefits can
    change without code checking plan names."""

    __tablename__ = "business_subscription_features"
    __table_args__ = (
        db.UniqueConstraint("plan_id", "feature_key", name="uq_plan_feature"),
    )

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(
        db.Integer,
        db.ForeignKey("business_subscription_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    feature_key = db.Column(db.String(50), nullable=False)
    # Optional numeric limit for features that have one; null means unlimited.
    limit_value = db.Column(db.Integer)

    plan = db.relationship("BusinessSubscriptionPlan", back_populates="features")


class BusinessSubscriptionStatus(Enum):
    PENDING = "pending"  # created, payment not confirmed
    ACTIVE = "active"
    CANCELLED = "cancelled"  # runs to end_date, does not renew
    EXPIRED = "expired"


class BusinessSubscription(BaseModel):
    __tablename__ = "business_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.String(12), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan_id = db.Column(
        db.Integer, db.ForeignKey("business_subscription_plans.id"), nullable=False
    )
    status = db.Column(
        db.Enum(BusinessSubscriptionStatus),
        default=BusinessSubscriptionStatus.PENDING,
        nullable=False,
    )
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    renewal_date = db.Column(db.DateTime)
    payment_reference = db.Column(db.String(100), unique=True)

    plan = db.relationship("BusinessSubscriptionPlan")
    user = db.relationship("User")
