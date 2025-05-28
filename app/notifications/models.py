from enum import Enum
from external.database import db
from sqlalchemy.dialects.postgresql import JSONB
from app.libs.models import BaseModel


class NotificationType(Enum):
    POST_LIKE = "post_like"
    POST_COMMENT = "post_comment"
    NEW_FOLLOWER = "new_follower"
    PRODUCT_LIKE = "product_like"
    PRODUCT_COMMENT = "product_comment"
    ORDER_UPDATE = "order_update"
    SHIPMENT_UPDATE = "shipment_update"
    PROMOTIONAL = "promotional"
    SYSTEM_ALERT = "system_alert"


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
            "created_at": self.created_at.isoformat(),
            "metadata_": self.metadata_ or {},
        }
