# python imports
import logging

# package imports
from sqlalchemy.exc import SQLAlchemyError

# project imports
from external.database import db
from external.redis import redis_client

from app.libs.session import session_scope
from app.libs.pagination import Paginator
from app.libs.errors import NotFoundError

# app imports
from .models import Notification, NotificationType

logger = logging.getLogger(__name__)


class NotificationService:
    # Notification templates
    TEMPLATES = {
        NotificationType.POST_LIKE: {
            "title": "New like",
            "message": "{username} liked your post",
        },
        NotificationType.POST_COMMENT: {
            "title": "New comment",
            "message": "{username} commented on your post",
        },
        NotificationType.NEW_FOLLOWER: {
            "title": "New follower",
            "message": "{username} started following you",
        },
        NotificationType.PRODUCT_LIKE: {
            "title": "Product liked",
            "message": "{username} liked your product {product_name}",
        },
        NotificationType.PRODUCT_COMMENT: {
            "title": "New product comment",
            "message": "{username} commented on your product {product_name}",
        },
        NotificationType.ORDER_UPDATE: {
            "title": "Order update",
            "message": "Your order #{order_id} status changed to {status}",
        },
    }

    @staticmethod
    def create_notification(
        user_id,
        notification_type,
        actor_id=None,
        reference_type=None,
        reference_id=None,
        metadata_=None,
    ):
        """Create and deliver a notification"""
        try:
            template = NotificationService.TEMPLATES.get(notification_type)
            if not template:
                raise ValueError(
                    f"No template for notification type {notification_type}"
                )

            # Get actor info if needed
            actor_name = None
            if actor_id:
                from app.users.models import User

                with session_scope() as session:
                    actor = session.query(User).get(actor_id)
                    if actor:
                        actor_name = actor.username

            # Format message
            message = template["message"].format(
                username=actor_name or "Someone",
                product_name=metadata_.get("product_name") if metadata_ else None,
                order_id=reference_id,
                status=metadata_.get("status") if metadata_ else None,
            )

            with session_scope() as session:
                notification = Notification(
                    user_id=user_id,
                    type=notification_type,
                    title=template["title"],
                    message=message,
                    is_read=False,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    metadata_=metadata_ or {},
                )
                session.add(notification)
                session.flush()

                # Real-time delivery
                NotificationService._deliver_notification(notification)

                return notification

        except Exception as e:
            logger.error(f"Notification creation failed: {str(e)}")
            raise

    @staticmethod
    def _deliver_notification(notification):
        """Deliver notification via multiple channels"""
        # 1. Real-time WebSocket
        redis_client.publish(
            f"notifications:{notification.user_id}", notification.to_dict()
        )

        # 2. Push notification (placeholder)
        if notification.type not in [NotificationType.SYSTEM_ALERT]:
            NotificationService._send_push_notification(notification)

        # 3. Email for important notifications (placeholder)
        if notification.type in [
            NotificationType.ORDER_UPDATE,
            NotificationType.SYSTEM_ALERT,
        ]:
            NotificationService._send_email_notification(notification)

    @staticmethod
    def _send_push_notification(notification):
        """Placeholder for push notification service"""

    @staticmethod
    def _send_email_notification(notification):
        """Placeholder for email notification service"""

    @staticmethod
    def get_user_notifications(user_id, page=1, per_page=20, unread_only=False):
        """Get paginated notifications for user"""
        try:
            with session_scope() as session:
                query = session.query(Notification).filter(
                    Notification.user_id == user_id
                )

                if unread_only:
                    query = query.filter(Notification.is_read == False)

                query = query.order_by(Notification.created_at.desc())

                paginator = Paginator(query, page=page, per_page=per_page)
                result = paginator.paginate({})

                return {
                    "items": result["items"],
                    "pagination": {
                        "page": result["page"],
                        "per_page": result["per_page"],
                        "total_items": result["total_items"],
                        "total_pages": result["total_pages"],
                    },
                }
        except SQLAlchemyError as e:
            logger.error(f"Error fetching notifications: {str(e)}")
            raise NotFoundError("Failed to fetch notifications")

    @staticmethod
    def mark_as_read(user_id, notification_ids=None):
        """Mark notifications as read"""
        try:
            with session_scope() as session:
                query = session.query(Notification).filter(
                    Notification.user_id == user_id, Notification.is_read == False
                )

                if notification_ids:
                    query = query.filter(Notification.id.in_(notification_ids))

                updated = query.update({"is_read": True}, synchronize_session=False)
                session.commit()

                # Send read receipt
                if updated > 0:
                    redis_client.publish(
                        f"notifications:{user_id}:read", {"count": updated}
                    )

                return updated
        except SQLAlchemyError as e:
            logger.error(f"Error marking notifications as read: {str(e)}")
            raise
