from enum import Enum
from flask_login import UserMixin
from datetime import datetime

from app.libs.models import BaseModel
from app.libs.helpers import UniqueIdMixin
from external.database import db
from external.redis import redis_client

CURRENT_ROLE_CACHE_KEY = "user:current_role:{user_id}"
CURRENT_ROLE_CACHE_TTL = 60 * 60 * 24  # 24 hours


class User(BaseModel, UserMixin, UniqueIdMixin):
    __tablename__ = "users"
    id_prefix = "USR_"

    id = db.Column(db.String(12), primary_key=True, default=None)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone_number = db.Column(db.String(20))
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    profile_picture = db.Column(db.String(255), default="default.jpg")

    is_buyer = db.Column(db.Boolean, default=False)
    is_seller = db.Column(db.Boolean, default=False)
    # Admin gate for app.libs.decorators.admin_required/_has_permission --
    # no self-serve path to set this; an admin sets it directly (DB or a
    # future internal tool), same "flagged permanently until someone
    # edits the DB" treatment already used for MarketVerificationStatus.FLAGGED
    # and SellerReliabilityScore.gaming_flagged.
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    deactivated_at = db.Column(db.DateTime)
    # Set when the user deletes their account (Apple App Store 5.1.1(v)).
    # Distinct from deactivated_at, which is reversible: once this is set the
    # row has already been stripped of personal data and can never be signed
    # into again. The row itself survives only so that posts, reviews, chat
    # threads and order history belonging to other people stay coherent --
    # see AccountDeletionService.
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    # Email verification
    email_verified = db.Column(db.Boolean, default=False)
    # Last login timestamp for session management
    last_login_at = db.Column(db.DateTime)

    # Relationships
    address = db.relationship("UserAddress", uselist=False, back_populates="user")
    buyer_account = db.relationship("Buyer", uselist=False, back_populates="user")
    seller_account = db.relationship("Seller", uselist=False, back_populates="user")
    settings = db.relationship(
        "UserSettings",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    requests = db.relationship("BuyerRequest", back_populates="user", lazy="dynamic")
    product_reviews = db.relationship(
        "ProductReview", back_populates="user", lazy="dynamic"
    )

    notifications = db.relationship(
        "Notification", back_populates="user", lazy="dynamic"
    )
    transactions = db.relationship("Transaction", back_populates="user", lazy="dynamic")
    wallet_accounts = db.relationship(
        "WalletAccount", back_populates="user", lazy="dynamic"
    )
    withdrawal_requests = db.relationship(
        "WithdrawalRequest", back_populates="user", lazy="dynamic"
    )
    wallet_topups = db.relationship(
        "WalletTopUp", back_populates="user", lazy="dynamic"
    )
    posts = db.relationship("Post", back_populates="user", lazy="dynamic")
    post_likes = db.relationship("PostLike", back_populates="user", lazy="dynamic")
    post_comments = db.relationship(
        "PostComment", back_populates="user", lazy="dynamic"
    )

    # Chat relationships
    buyer_chats = db.relationship(
        "ChatRoom",
        foreign_keys="[ChatRoom.buyer_id]",
        back_populates="buyer",
        lazy="dynamic",
    )
    seller_chats = db.relationship(
        "ChatRoom",
        foreign_keys="[ChatRoom.seller_id]",
        back_populates="seller",
        lazy="dynamic",
    )
    sent_messages = db.relationship(
        "ChatMessage", back_populates="sender", lazy="dynamic"
    )

    # Social features
    followers = db.relationship(
        "Follow",
        foreign_keys="[Follow.followee_id]",
        back_populates="followee",
        lazy="dynamic",
    )
    following = db.relationship(
        "Follow",
        foreign_keys="[Follow.follower_id]",
        back_populates="follower",
        lazy="dynamic",
    )

    # Media relationships
    media_uploads = db.relationship("Media", back_populates="user", lazy="dynamic")

    def set_password(self, password):
        from passlib.hash import pbkdf2_sha256

        self.password_hash = pbkdf2_sha256.hash(password)

    def check_password(self, password):
        from passlib.hash import pbkdf2_sha256

        # Account deletion destroys the hash outright, and passlib raises on a
        # null hash rather than returning False -- which would surface as a 500
        # instead of "invalid credentials".
        if not self.password_hash:
            return False
        return pbkdf2_sha256.verify(password, self.password_hash)

    @property
    def current_role(self):
        """Get current role with intelligent defaulting"""
        # If explicitly set, return it
        if hasattr(self, "_current_role") and self._current_role:
            return self._current_role

        # Attempt to restore from cache to maintain user preference across sessions
        try:
            cache_key = CURRENT_ROLE_CACHE_KEY.format(user_id=self.id)
            cached_role = redis_client.get(cache_key)
            if cached_role:
                if isinstance(cached_role, bytes):
                    cached_role = cached_role.decode("utf-8")
                if cached_role in {"buyer", "seller"}:
                    self._current_role = cached_role
                    return cached_role
        except Exception:
            # Redis failures should not break role determination
            pass

        # Otherwise, determine based on available accounts
        # Priority: buyer > seller (consistent with login defaults)
        if self.is_buyer and self.is_seller:
            return "buyer"  # Default to buyer for dual-account users
        elif self.is_buyer:
            return "buyer"
        elif self.is_seller:
            return "seller"
        else:
            return "buyer"  # Fallback default

    @current_role.setter
    def current_role(self, value):
        if value not in ["buyer", "seller"]:
            raise ValueError("Invalid role")
        if value == "buyer" and not self.is_buyer:
            raise ValueError("User doesn't have buyer account")
        if value == "seller" and not self.is_seller:
            raise ValueError("User doesn't have seller account")
        self._current_role = value
        try:
            cache_key = CURRENT_ROLE_CACHE_KEY.format(user_id=self.id)
            redis_client.setex(cache_key, CURRENT_ROLE_CACHE_TTL, value)
        except Exception:
            # Redis failures shouldn't break role switching
            pass

    def deactivate(self):
        """Deactivate user account"""
        self.is_active = False
        self.deactivated_at = datetime.utcnow()

    def activate(self):
        """Reactivate user account"""
        self.is_active = True
        self.deactivated_at = None


class SocialAccount(BaseModel):
    """A verified third-party identity linked to a Markt user.

    Keyed on (provider, provider_sub) rather than email, deliberately. `sub` is
    the provider's stable, immutable subject id; an email can be changed by the
    user, and Apple's private-relay addresses can be revoked entirely. Matching
    on email would mean losing the link the moment either happens.

    One row per (provider, user), so a user can hold both a Google and an Apple
    identity, but a single provider identity can never point at two accounts.
    """

    __tablename__ = "social_accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.String(12), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider = db.Column(db.String(16), nullable=False)  # "google" | "apple"

    # The provider's subject claim. Unique per provider, never reused.
    provider_sub = db.Column(db.String(255), nullable=False)

    # What the provider told us at link time, kept for support questions.
    # Apple sends the name exactly once, on first authorisation, so if it is
    # not captured here it is gone for good.
    email_at_link = db.Column(db.String(255), nullable=True)
    name_at_link = db.Column(db.String(255), nullable=True)

    # True when the provider asserted the email was verified. Drives whether an
    # email collision may auto-link; an unverified provider email would
    # otherwise be an account-takeover vector.
    email_verified_at_link = db.Column(db.Boolean, nullable=False, default=False)

    linked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref=db.backref("social_accounts", lazy=True))

    __table_args__ = (
        db.UniqueConstraint("provider", "provider_sub", name="uq_social_provider_sub"),
        db.UniqueConstraint("provider", "user_id", name="uq_social_provider_user"),
    )


class Buyer(BaseModel):
    __tablename__ = "buyers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    buyername = db.Column(db.String(50))
    shipping_address = db.Column(db.JSON)
    is_active = db.Column(db.Boolean, default=True)
    deactivated_at = db.Column(db.DateTime)

    # Relationships
    user = db.relationship("User", back_populates="buyer_account")
    carts = db.relationship(
        "Cart", back_populates="buyer", cascade="all, delete-orphan"
    )
    orders = db.relationship("Order", back_populates="buyer", lazy="dynamic")

    def deactivate(self):
        """Deactivate buyer account"""
        self.is_active = False
        self.deactivated_at = datetime.utcnow()

    def activate(self):
        """Reactivate buyer account"""
        self.is_active = True
        self.deactivated_at = None


class SellerVerificationStatus(Enum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class MarketVerificationStatus(Enum):
    """Separate from SellerVerificationStatus (business/KYC identity) --
    this is specifically about whether a seller's claimed Market matches
    where their shop address actually geocodes to. See
    app.markets.services.MarketService.assign_seller_market."""

    UNVERIFIED = "unverified"  # no market claimed yet, or nothing to check against
    VERIFIED = "verified"  # geocoded shop address within tolerance of the market
    FLAGGED = "flagged"  # outside tolerance -- excluded from rerouting until reviewed


class Seller(BaseModel):
    __tablename__ = "sellers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    shop_name = db.Column(db.String(100))
    shop_slug = db.Column(db.String(110), unique=True)
    description = db.Column(db.Text)
    # Shop cover image. profile_picture on User is the shop's avatar; this is
    # the wide image behind it on a shop card. Stored as a URL for the same
    # reason User.profile_picture is: the media row is the source of truth,
    # this is the denormalised read path so a shop list does not join media.
    banner_url = db.Column(db.String(500), nullable=True)
    policies = db.Column(db.JSON)  # Return, shipping policies
    total_rating = db.Column(db.Integer, default=0)
    total_raters = db.Column(db.Integer, default=0)
    verification_status = db.Column(
        db.Enum(SellerVerificationStatus), default=SellerVerificationStatus.UNVERIFIED
    )
    is_active = db.Column(db.Boolean, default=True)
    deactivated_at = db.Column(db.DateTime)
    paystack_subaccount_code = db.Column(db.String(50), nullable=True)
    payout_bank_code = db.Column(db.String(10), nullable=True)
    payout_account_number = db.Column(db.String(20), nullable=True)
    payout_account_name = db.Column(db.String(100), nullable=True)
    # Market membership (7.2, Phase 6) -- explicit assignment, not
    # geofenced. shop_address/lat/lng are only used to sanity-check the
    # claim (see market_verification_status), never to derive it.
    market_id = db.Column(db.Integer, db.ForeignKey("markets.id"), nullable=True)
    shop_address = db.Column(db.JSON, nullable=True)
    shop_latitude = db.Column(db.Float, nullable=True)
    shop_longitude = db.Column(db.Float, nullable=True)
    market_verification_status = db.Column(
        db.Enum(MarketVerificationStatus),
        default=MarketVerificationStatus.UNVERIFIED,
        nullable=False,
    )

    market = db.relationship("Market")

    # Relationships
    user = db.relationship("User", back_populates="seller_account")
    products = db.relationship("Product", back_populates="seller", lazy="dynamic")
    order_items = db.relationship("OrderItem", back_populates="seller")
    offers = db.relationship("SellerOffer", back_populates="seller", lazy="dynamic")
    transactions = db.relationship("Transaction", back_populates="seller")
    categories = db.relationship("SellerCategory", back_populates="seller")

    @property
    def pending_order_count(self):
        from app.orders.models import OrderItem

        return (
            db.session.query(OrderItem)
            .filter_by(seller_id=self.id, status="pending")
            .count()
        )

    def get_earnings(self, period="month"):
        """Calculate earnings for given period"""
        from sqlalchemy import func
        from datetime import datetime, timedelta
        from app.orders.models import Order, OrderItem

        if period == "month":
            date_filter = datetime.utcnow() - timedelta(days=30)
        elif period == "week":
            date_filter = datetime.utcnow() - timedelta(days=7)
        else:
            date_filter = None

        query = db.session.query(
            func.sum(OrderItem.price * OrderItem.quantity)
        ).filter_by(seller_id=self.id)

        if date_filter:
            query = query.join(Order).filter(Order.created_at >= date_filter)

        return query.scalar() or 0

    def deactivate(self):
        """Deactivate user account"""
        self.is_active = False
        self.deactivated_at = datetime.utcnow()

    def activate(self):
        """Reactivate user account"""
        self.is_active = True
        self.deactivated_at = None


class UserAddress(BaseModel):
    __tablename__ = "user_addresses"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    longitude = db.Column(db.Float)
    latitude = db.Column(db.Float)
    house_number = db.Column(db.String(20))
    street = db.Column(db.String(100))
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    country = db.Column(db.String(100))
    postal_code = db.Column(db.String(20))

    user = db.relationship("User", back_populates="address")


class UserSettings(BaseModel):
    __tablename__ = "user_settings"

    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), primary_key=True)
    email_notifications = db.Column(db.Boolean, default=True)
    push_notifications = db.Column(db.Boolean, default=True)
    sms_notifications = db.Column(db.Boolean, default=False)
    privacy_public_profile = db.Column(db.Boolean, default=False)
    preferred_language = db.Column(db.String(5), default="en")

    user = db.relationship("User", back_populates="settings", uselist=False)
