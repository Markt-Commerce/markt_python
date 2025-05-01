from app.libs.models import BaseModel
from app.libs.helper import UniqueIdMixin
from external.database import db
from flask_login import UserMixin


class User(BaseModel, UserMixin, UniqueIdMixin):
    __tablename__ = "users"
    id_prefix = "USR_"

    id = db.Column(db.String(12), primary_key=True, default=None)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone_number = db.Column(db.String(20))
    username = db.Column(db.String(50), unique=True, nullable=False)
    profile_picture = db.Column(db.String(255), default="default.jpg")

    is_buyer = db.Column(db.Boolean, default=False)
    is_seller = db.Column(db.Boolean, default=False)

    # Relationships
    address = db.relationship("UserAddress", uselist=False, back_populates="user")
    buyer_account = db.relationship("Buyer", uselist=False, back_populates="user")
    seller_account = db.relationship("Seller", uselist=False, back_populates="user")
    requests = db.relationship("BuyerRequest", back_populates="user", lazy="dynamic")
    notifications = db.relationship(
        "Notification", back_populates="user", lazy="dynamic"
    )
    transactions = db.relationship("Transaction", back_populates="user", lazy="dynamic")
    product_likes = db.relationship(
        "ProductLike", back_populates="user", lazy="dynamic"
    )
    product_comments = db.relationship(
        "ProductComment", back_populates="user", lazy="dynamic"
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

    @property
    def current_role(self):
        return getattr(self, "_current_role", "buyer" if self.is_buyer else "seller")

    @current_role.setter
    def current_role(self, value):
        if value not in ["buyer", "seller"]:
            raise ValueError("Invalid role")
        if value == "buyer" and not self.is_buyer:
            raise ValueError("User doesn't have buyer account")
        if value == "seller" and not self.is_seller:
            raise ValueError("User doesn't have seller account")
        self._current_role = value


class Buyer(BaseModel):
    __tablename__ = "buyers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    buyername = db.Column(db.String(50))
    password_hash = db.Column(db.String(128))
    shipping_address = db.Column(db.JSON)

    # Relationships
    user = db.relationship("User", back_populates="buyer_account")
    carts = db.relationship(
        "Cart", back_populates="buyer", cascade="all, delete-orphan"
    )
    orders = db.relationship("Order", back_populates="buyer", lazy="dynamic")
    # requests = db.relationship("BuyerRequest", back_populates="buyer", lazy="dynamic")
    # favorites = db.relationship("ProductLike", back_populates="buyer", lazy="dynamic")

    def set_password(self, password):
        from passlib.hash import pbkdf2_sha256

        self.password_hash = pbkdf2_sha256.hash(password)

    def check_password(self, password):
        from passlib.hash import pbkdf2_sha256

        return pbkdf2_sha256.verify(password, self.password_hash)


class Seller(BaseModel):
    __tablename__ = "sellers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    shop_name = db.Column(db.String(100))
    password_hash = db.Column(db.String(128))
    description = db.Column(db.String(500))
    category = db.Column(db.String(100))
    total_rating = db.Column(db.Integer, default=0)
    total_raters = db.Column(db.Integer, default=0)

    # Relationships
    user = db.relationship("User", back_populates="seller_account")
    products = db.relationship("Product", back_populates="seller", lazy="dynamic")
    orders = db.relationship("Order", back_populates="seller", lazy="dynamic")
    offers = db.relationship("SellerOffer", back_populates="seller", lazy="dynamic")

    def set_password(self, password):
        from passlib.hash import pbkdf2_sha256

        self.password_hash = pbkdf2_sha256.hash(password)

    def check_password(self, password):
        from passlib.hash import pbkdf2_sha256

        return pbkdf2_sha256.verify(password, self.password_hash)


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
