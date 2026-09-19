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
    # A rider moved a delivery forward -- accepted it, reached the shop,
    # collected the parcel, set off, arrived. The buyer got none of this:
    # every notification about their own order stopped at "paid", and the
    # rest of it happened silently behind a status string they had to open
    # the app and pull to refresh to see.
    DELIVERY_STATUS_UPDATE = "delivery_status_update"
    # The seller's half of the same events, and only the two that ask
    # something of them: a rider is coming, and a rider is outside.
    DELIVERY_PICKUP_UPDATE = "delivery_pickup_update"
    # Any of the three refund paths (cancel_order, refund_unresolved_item,
    # approve_return) actually credited the buyer's wallet.
    REFUND_ISSUED = "refund_issued"
    # Social notifications
    NICHE_INVITATION = "niche_invitation"
    NICHE_POST_APPROVED = "niche_post_approved"
    NICHE_POST_REJECTED = "niche_post_rejected"
    MODERATION_ACTION = "moderation_action"
    CHAT_MESSAGE = "chat_message"
    CHAT_OFFER = "chat_offer"
    CHAT_OFFER_RESPONSE = "chat_offer_response"
    WALLET_TOPUP_COMPLETED = "wallet_topup_completed"
    WALLET_TOPUP_FAILED = "wallet_topup_failed"
    WITHDRAWAL_COMPLETED = "withdrawal_completed"
    WITHDRAWAL_FAILED = "withdrawal_failed"

    # Riders. Their own types rather than reusing the buyer/seller ones: a
    # rider's "new delivery available" is not a buyer's "order update", and
    # collapsing them would mean one channel policy and one wording for two
    # audiences with nothing in common.
    DELIVERY_AVAILABLE = "delivery_available"
    DELIVERY_ASSIGNED = "delivery_assigned"
    DELIVERY_EARNING_CREDITED = "delivery_earning_credited"


class Notification(BaseModel):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    # Exactly one of user_id/delivery_user_id is set, like WalletAccount.
    # DeliveryUser is a structurally separate table from User (delivery_users
    # vs users, DEL_ vs USR_ ids), so a rider could not be notified at all --
    # the FK refused the row, and every notification call swallows its own
    # failure, so nothing said so.
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=True)
    delivery_user_id = db.Column(
        db.String(12), db.ForeignKey("delivery_users.id"), nullable=True, index=True
    )
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
        db.CheckConstraint(
            "(user_id IS NOT NULL) <> (delivery_user_id IS NOT NULL)",
            name="ck_notifications_single_owner",
        ),
    )

    user = db.relationship("User", back_populates="notifications")
    delivery_user = db.relationship("DeliveryUser")

    @property
    def owner_id(self) -> str:
        """Whoever this notification is for, whichever column holds them."""
        return self.user_id or self.delivery_user_id

    def to_dict(self):
        return {
            "id": self.id,
            # Who it is for.
            #
            # This was missing, and deliver_notification -- the task that
            # dispatches push and email -- reads notification_data["user_id"]
            # first thing. So every queued delivery raised KeyError before it
            # began: push and notification email have never been sent at all,
            # while the websocket path kept working because it is called
            # directly with the id rather than from this payload.
            #
            # owner_id, so a rider's notification carries the rider.
            "user_id": self.owner_id,
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
    # Same single-owner rule as Notification above: without this a rider's
    # device could not register for push, so the rider app had nowhere to send
    # a token even once it asked for one.
    user_id = db.Column(
        db.String(12), db.ForeignKey("users.id"), nullable=True, index=True
    )
    delivery_user_id = db.Column(
        db.String(12), db.ForeignKey("delivery_users.id"), nullable=True, index=True
    )
    token = db.Column(db.String(255), nullable=False, unique=True)
    platform = db.Column(db.String(20), nullable=True)  # ios / android

    __table_args__ = (
        db.CheckConstraint(
            "(user_id IS NOT NULL) <> (delivery_user_id IS NOT NULL)",
            name="ck_push_tokens_single_owner",
        ),
    )

    @property
    def owner_id(self) -> str:
        return self.user_id or self.delivery_user_id
