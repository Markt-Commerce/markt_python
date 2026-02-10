from external.database import db
from app.libs.models import BaseModel, ReactionMixin, BaseReaction
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declared_attr


class ChatRoom(BaseModel):
    __tablename__ = "chat_rooms"

    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    seller_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"), nullable=True)
    request_id = db.Column(
        db.String(12), db.ForeignKey("buyer_requests.id"), nullable=True
    )
    last_message_at = db.Column(db.DateTime)
    unread_count_buyer = db.Column(db.Integer, default=0)
    unread_count_seller = db.Column(db.Integer, default=0)

    # Relationships
    buyer = db.relationship(
        "User", foreign_keys=[buyer_id], back_populates="buyer_chats"
    )
    seller = db.relationship(
        "User", foreign_keys=[seller_id], back_populates="seller_chats"
    )
    product = db.relationship("Product")
    request = db.relationship("BuyerRequest")
    messages = db.relationship(
        "ChatMessage", back_populates="room", order_by="ChatMessage.created_at"
    )
    discounts = db.relationship(
        "ChatDiscount", back_populates="room", order_by="ChatDiscount.created_at"
    )


class ChatMessage(BaseModel, ReactionMixin):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("chat_rooms.id"))
    sender_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    content = db.Column(db.Text)
    message_type = db.Column(
        db.String(20), default="text"
    )  # text, image, product, offer, discount, discount_response
    message_data = db.Column(
        JSONB
    )  # For additional data like product details, offer terms
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime)

    # Relationships
    room = db.relationship("ChatRoom", back_populates="messages")
    sender = db.relationship("User", back_populates="sent_messages")


class ChatOffer(BaseModel):
    __tablename__ = "chat_offers"

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("chat_messages.id"))
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"))
    price = db.Column(db.Float)
    status = db.Column(db.String(20), default="pending")  # pending/accepted/rejected

    message = db.relationship("ChatMessage", foreign_keys=[message_id])
    product = db.relationship("Product")


class DiscountType:
    """Discount type constants"""

    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"


class DiscountStatus:
    """Discount status constants"""

    PENDING = "pending"
    ACTIVE = "active"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    USED = "used"
    CANCELLED = "cancelled"


class ChatDiscount(BaseModel):
    """Discount offers created within chat conversations"""

    __tablename__ = "chat_discounts"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("chat_rooms.id"))
    message_id = db.Column(db.Integer, db.ForeignKey("chat_messages.id"), nullable=True)
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"), nullable=True)

    # Discount details
    discount_type = db.Column(
        db.String(20), nullable=False
    )  # percentage or fixed_amount
    discount_value = db.Column(
        db.Float, nullable=False
    )  # percentage (0-100) or fixed amount
    minimum_order_amount = db.Column(
        db.Float, nullable=True
    )  # minimum order for discount
    maximum_discount_amount = db.Column(
        db.Float, nullable=True
    )  # cap for percentage discounts

    # Validity and usage
    expires_at = db.Column(db.DateTime, nullable=False)
    usage_limit = db.Column(db.Integer, default=1)  # how many times it can be used
    usage_count = db.Column(db.Integer, default=0)  # how many times it has been used

    # Status and participants
    status = db.Column(db.String(20), default=DiscountStatus.PENDING)
    created_by_id = db.Column(
        db.String(12), db.ForeignKey("users.id"), nullable=False
    )  # seller
    offered_to_id = db.Column(
        db.String(12), db.ForeignKey("users.id"), nullable=False
    )  # buyer

    # Optional message and metadata
    discount_message = db.Column(db.Text, nullable=True)  # custom message from seller
    discount_code = db.Column(db.String(50), nullable=True)  # optional custom code
    discount_metadata = db.Column(JSONB)  # additional discount data

    # Timestamps for status changes
    accepted_at = db.Column(db.DateTime, nullable=True)
    rejected_at = db.Column(db.DateTime, nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    room = db.relationship("ChatRoom", back_populates="discounts")
    message = db.relationship("ChatMessage", foreign_keys=[message_id])
    product = db.relationship("Product")
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    offered_to = db.relationship("User", foreign_keys=[offered_to_id])

    def is_valid(self):
        """Check if discount is still valid"""
        from app.libs.datetime_utils import ensure_timezone_aware, utcnow_aware

        expires_at_aware = ensure_timezone_aware(self.expires_at)
        now_aware = utcnow_aware()

        return (
            self.status
            in [DiscountStatus.PENDING, DiscountStatus.ACTIVE, DiscountStatus.ACCEPTED]
            and expires_at_aware > now_aware
            and self.usage_count < self.usage_limit
        )

    def calculate_discount_amount(self, order_amount: float) -> float:
        """Calculate the actual discount amount for a given order"""
        if not self.is_valid():
            return 0.0

        if self.discount_type == DiscountType.PERCENTAGE:
            discount_amount = (order_amount * self.discount_value) / 100
            # Apply maximum discount cap if set
            if self.maximum_discount_amount:
                discount_amount = min(discount_amount, self.maximum_discount_amount)
        else:  # FIXED_AMOUNT
            discount_amount = self.discount_value

        # Ensure discount doesn't exceed order amount
        return min(discount_amount, order_amount)

    def can_be_applied_to_order(self, order_amount: float) -> tuple[bool, str]:
        """Check if discount can be applied to an order with validation message"""
        if not self.is_valid():
            if self.status == DiscountStatus.EXPIRED:
                return False, "Discount has expired"
            elif self.status == DiscountStatus.USED:
                return False, "Discount has already been used"
            elif self.status in [DiscountStatus.REJECTED, DiscountStatus.CANCELLED]:
                return False, "Discount is no longer available"
            else:
                return False, "Discount is not valid"

        if self.minimum_order_amount and order_amount < self.minimum_order_amount:
            return (
                False,
                f"Minimum order amount of ${self.minimum_order_amount:.2f} required",
            )

        if self.usage_count >= self.usage_limit:
            return False, "Discount usage limit reached"

        return True, "Discount can be applied"


# Reaction Model for Chat Messages
class ChatMessageReaction(BaseReaction):
    __tablename__ = "chat_message_reactions"

    message_id = db.Column(
        db.Integer, db.ForeignKey("chat_messages.id"), nullable=False
    )

    # Relationships
    @declared_attr
    def content(cls):
        return db.relationship("ChatMessage", back_populates="reactions")

    __table_args__ = (
        db.UniqueConstraint(
            "message_id", "user_id", "reaction_type", name="uq_chat_message_reaction"
        ),
        db.Index("idx_chat_message_reaction_message", "message_id"),
        db.Index("idx_chat_message_reaction_user", "user_id"),
        db.Index("idx_chat_message_reaction_type", "reaction_type"),
    )
