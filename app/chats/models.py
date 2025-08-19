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


class ChatMessage(BaseModel, ReactionMixin):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("chat_rooms.id"))
    sender_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    content = db.Column(db.Text)
    message_type = db.Column(
        db.String(20), default="text"
    )  # text, image, product, offer
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
