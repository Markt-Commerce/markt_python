import logging
from datetime import datetime, timedelta
from typing import Dict, List

from main.workers import celery_app
from external.redis import redis_client
from app.libs.session import session_scope

from .models import Notification, NotificationType

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def deliver_notification(self, notification_data: Dict, channels: List[str]):
    """
    Asynchronously deliver notification via specified channels
    """
    try:
        user_id = notification_data["user_id"]
        notification_data["type"]

        for channel in channels:
            try:
                if channel == "push":  # DeliveryChannel.PUSH.value
                    send_push_notification.delay(notification_data)
                elif channel == "email":  # DeliveryChannel.EMAIL.value
                    send_email_notification.delay(notification_data)
                elif channel == "websocket":  # DeliveryChannel.WEBSOCKET.value
                    from main.extensions import socketio

                    # Fallback WebSocket delivery (if immediate delivery failed)
                    socketio.emit(
                        "notification",
                        notification_data,
                        room=f"user_{user_id}",
                        namespace="/notifications",
                    )
                    # Update unread count
                    unread_count = get_unread_count(user_id)
                    socketio.emit(
                        "unread_count_update",
                        {"count": unread_count},
                        room=f"user_{user_id}",
                        namespace="/notifications",
                    )

            except Exception as channel_error:
                logger.error(
                    f"Failed to deliver via {channel} for user {user_id}: {str(channel_error)}"
                )
                # Continue with other channels even if one fails

        logger.info(
            f"Async notification delivery completed for user {user_id} via channels: {channels}"
        )

    except Exception as e:
        logger.error(f"Notification delivery task failed: {str(e)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2**self.request.retries))
        raise


@celery_app.task(bind=True)
def send_push_notification(self, notification_data: Dict):
    """Send push notification to mobile devices"""
    try:
        # Placeholder for push notification service integration
        # Example: FCM, APNs, etc.
        logger.info(
            f"Push notification sent for notification {notification_data['id']}"
        )
    except Exception as e:
        logger.error(f"Push notification failed: {str(e)}")


@celery_app.task(bind=True)
def send_email_notification(self, notification_data: Dict):
    """Send email notification for important alerts"""
    try:
        # Placeholder for email service integration
        logger.info(
            f"Email notification sent for notification {notification_data['id']}"
        )
    except Exception as e:
        logger.error(f"Email notification failed: {str(e)}")


@celery_app.task
def cleanup_old_notifications():
    """Clean up old read notifications (keep for 30 days)"""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        with session_scope() as session:
            deleted = (
                session.query(Notification)
                .filter(
                    Notification.is_read == True, Notification.created_at < cutoff_date
                )
                .delete()
            )
            session.commit()
            logger.info(f"Cleaned up {deleted} old notifications")
    except Exception as e:
        logger.error(f"Notification cleanup failed: {str(e)}")


def get_unread_count(user_id: str) -> int:
    """Get unread notification count for user"""
    try:
        with session_scope() as session:
            return (
                session.query(Notification)
                .filter(Notification.user_id == user_id, Notification.is_read == False)
                .count()
            )
    except Exception as e:
        logger.error(f"Error getting unread count: {str(e)}")
        return 0


def _is_user_online(user_id: str) -> bool:
    """Check if user is currently online via SocketIO"""
    try:
        # Check if user has active socket connections
        return redis_client.exists(f"online_users:{user_id}")
    except Exception:
        return False
