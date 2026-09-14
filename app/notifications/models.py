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
    # 7.4: a new request matching a seller's category (and, for a
    # REROUTE_ENGINE request, their market) has opened -- distinct from
    # REQUEST_OFFER, which notifies the *buyer* that a seller responded.
    NEW_REQUEST_MATCH = "new_request_match"
    # Cart and order notifications
    CART_ITEM_ADDED = "cart_item_added"
    ORDER_PLACED = "order_placed"
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    # Seller fulfilment notifications (12.1-12.2)
    FULFILMENT_REQUEST = "fulfilment_request"
    # 6.1 ASK gate: a reroute-created substitution needs buyer approval
    # before it commits.
    SUBSTITUTION_APPROVAL_REQUIRED = "substitution_approval_required"
    # 10.3: this order's delivery run doesn't have enough sharing yet --
    # wait for a fuller run (default) or pay now for single/near-single
    # delivery.
    THIN_VOLUME_DELIVERY_CHOICE = "thin_volume_delivery_choice"
    # Phase 12 (15): rerouting genuinely exhausted, no replacement found --
    # see app.fulfilment.rerouting's ITEM_UNFULFILLED event-log emission,
    # which this is fired alongside.
    ITEM_UNFULFILLED = "item_unfulfilled"
    # Buyer-initiated whole-order cancellation (OrderService.cancel_order).
    ORDER_CANCELLED = "order_cancelled"
    # 10.7: a rider reported a failed delivery attempt for this order.
    DELIVERY_FAILED = "delivery_failed"
    # Any of the three refund paths (cancel_order, refund_unresolved_item,
    # approve_return) actually credited the buyer's wallet.
    REFUND_ISSUED = "refund_issued"
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


class PushToken(BaseModel):
    """A device's Expo push token, for remote push notifications."""

    __tablename__ = "push_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.String(12), db.ForeignKey("users.id"), nullable=False, index=True
    )
    token = db.Column(db.String(255), nullable=False, unique=True)
    platform = db.Column(db.String(20), nullable=True)  # ios / android
