from enum import Enum
from external.database import db
from sqlalchemy.dialects.postgresql import JSONB
from app.libs.models import BaseModel


class NotificationType(Enum):
    POST_LIKE = "post_like"
    POST_COMMENT = "post_comment"
    NEW_FOLLOWER = "new_follower"
    PRODUCT_REVIEW = "product_review"
    REVIEW_UPVOTE = "review_upvote"
    ORDER_UPDATE = "order_update"
    SHIPMENT_UPDATE = "shipment_update"
    PROMOTIONAL = "promotional"
    SYSTEM_ALERT = "system_alert"
    # Buyer request notifications
    REQUEST_OFFER = "request_offer"
    OFFER_ACCEPTED = "offer_accepted"
    OFFER_REJECTED = "offer_rejected"
    OFFER_WITHDRAWN = "offer_withdrawn"
    REQUEST_CLOSED = "request_closed"
    REQUEST_STATUS_CHANGE = "request_status_change"
    REQUEST_EXPIRED = "request_expired"
    # Cart and order notifications
    CART_ITEM_ADDED = "cart_item_added"
    ORDER_PLACED = "order_placed"
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    # Social notifications
    NICHE_INVITATION = "niche_invitation"
    NICHE_POST_APPROVED = "niche_post_approved"
    NICHE_POST_REJECTED = "niche_post_rejected"
    MODERATION_ACTION = "moderation_action"


class Notification(BaseModel):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=False)
    type = db.Column(db.Enum(NotificationType), nullable=False)
    title = db.Column(db.String(100))
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    is_seen = db.Column(db.Boolean, default=False)  # Appeared in UI
    reference_type = db.Column(db.String(50))  # 'post', 'product', 'order', 'user'
    reference_id = db.Column(db.String(12))  # ID of related entity
    metadata_ = db.Column(JSONB)  # Flexible data storage
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        db.Index("idx_notification_user_unread", "user_id", "is_read"),
        db.Index("idx_notification_user_type", "user_id", "type"),
    )

    user = db.relationship("User", back_populates="notifications")

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type.value,
            "title": self.title,
            "message": self.message,
            "is_read": self.is_read,
            "reference_type": self.reference_type,
            "reference_id": self.reference_id,
            "created_at": self.created_at,
            "metadata_": self.metadata_ or {},
        }
