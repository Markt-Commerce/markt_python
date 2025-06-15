import logging
from flask_socketio import Namespace, emit, join_room, leave_room
from flask_login import current_user
from external.redis import redis_client

logger = logging.getLogger(__name__)


class NotificationNamespace(Namespace):
    def on_connect(self):
        """Handle client connection"""
        if not current_user.is_authenticated:
            logger.warning("Unauthorized connection attempt")
            return emit("error", {"message": "Unauthorized"})

        # Join user-specific room
        user_room = f"user_{current_user.id}"
        join_room(user_room)

        # Mark user as online
        redis_client.set(f"online_users:{current_user.id}", "1", ex=300)  # 5 min TTL

        # Send current unread count
        from .services import NotificationService

        unread_count = NotificationService.get_unread_count(current_user.id)
        emit("unread_count_update", {"count": unread_count})

        logger.info(f"User {current_user.id} connected to notifications")

    def on_disconnect(self):
        """Handle client disconnection"""
        if current_user.is_authenticated:
            user_room = f"user_{current_user.id}"
            leave_room(user_room)

            # Remove online status
            redis_client.delete(f"online_users:{current_user.id}")

            logger.info(f"User {current_user.id} disconnected from notifications")

    def on_mark_as_read(self, data):
        """Handle mark as read request via socket"""
        if not current_user.is_authenticated:
            return emit("error", {"message": "Unauthorized"})

        try:
            from .services import NotificationService

            notification_ids = data.get("notification_ids")
            updated = NotificationService.mark_as_read(
                current_user.id, notification_ids
            )

            emit("mark_read_response", {"success": True, "updated": updated})

        except Exception as e:
            logger.error(f"Error marking notifications as read: {str(e)}")
            emit("mark_read_response", {"success": False, "error": str(e)})

    def on_ping(self, data):
        """Handle ping to keep connection alive"""
        if current_user.is_authenticated:
            # Refresh online status
            redis_client.set(f"online_users:{current_user.id}", "1", ex=300)
            emit("pong", {"timestamp": data.get("timestamp")})
