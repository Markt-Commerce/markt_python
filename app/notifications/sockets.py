import logging
from datetime import datetime
from flask_socketio import Namespace, emit, join_room, leave_room
from flask_login import current_user
from external.redis import redis_client

logger = logging.getLogger(__name__)


class NotificationNamespace(Namespace):
    """Enhanced notification namespace with rate limiting and validation"""

    # Rate limiting configuration
    RATE_LIMITS = {
        "mark_as_read": {"max_calls": 20, "window": 60},  # 20 mark as read per minute
        "ping": {"max_calls": 30, "window": 60},  # 30 pings per minute
    }

    def _check_rate_limit(self, event_type: str, user_id: str) -> bool:
        """Check if user has exceeded rate limit for event type"""
        try:
            key = f"rate_limit:notifications:{event_type}:{user_id}"
            current = redis_client.get(key)

            if current and int(current) >= self.RATE_LIMITS[event_type]["max_calls"]:
                return False

            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, self.RATE_LIMITS[event_type]["window"])
            pipe.execute()

            return True
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            return True  # Allow if rate limiting fails

    def _validate_data(self, data: dict, required_fields: list) -> tuple[bool, str]:
        """Validate incoming data"""
        if not data:
            return False, "No data provided"

        for field in required_fields:
            if field not in data:
                return False, f"Missing required field: {field}"

        return True, ""

    def on_connect(self):
        """Handle client connection with enhanced error handling"""
        from main.sockets import SocketManager

        try:
            if not current_user.is_authenticated:
                logger.warning("Unauthorized notification connection attempt")
                return emit("error", {"message": "Unauthorized"})

            # Join user-specific room
            user_room = f"user_{current_user.id}"
            join_room(user_room)

            # Mark user as online using centralized manager
            SocketManager.mark_user_online(current_user.id, "notifications")

            # Send current unread count
            from .services import NotificationService

            unread_count = NotificationService.get_unread_count(current_user.id)
            emit(
                "unread_count_update",
                {"count": unread_count, "timestamp": datetime.utcnow().isoformat()},
            )

            logger.info(f"User {current_user.id} connected to notifications namespace")

        except Exception as e:
            logger.error(f"Notification connection error: {e}")
            emit("error", {"message": "Connection failed"})

    def on_disconnect(self):
        """Handle client disconnection"""
        from main.sockets import SocketManager

        try:
            if current_user.is_authenticated:
                user_room = f"user_{current_user.id}"
                leave_room(user_room)

                # Remove online status using centralized manager
                SocketManager.mark_user_offline(current_user.id)

                logger.info(
                    f"User {current_user.id} disconnected from notifications namespace"
                )

        except Exception as e:
            logger.error(f"Notification disconnection error: {e}")

    def on_mark_as_read(self, data):
        """Handle mark as read request via socket with validation"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("mark_as_read", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["notification_ids"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            notification_ids = data.get("notification_ids")

            # Validate notification IDs are integers
            if not isinstance(notification_ids, list):
                return emit("error", {"message": "notification_ids must be a list"})

            try:
                notification_ids = [int(nid) for nid in notification_ids]
            except (ValueError, TypeError):
                return emit("error", {"message": "Invalid notification IDs"})

            from .services import NotificationService

            updated = NotificationService.mark_as_read(
                current_user.id, notification_ids
            )

            emit(
                "mark_read_response",
                {
                    "success": True,
                    "updated": updated,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Error marking notifications as read: {str(e)}")
            emit(
                "mark_read_response",
                {
                    "success": False,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

    def on_ping(self, data):
        """Handle ping to keep connection alive with rate limiting"""
        from main.sockets import SocketManager

        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("ping", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Refresh online status using centralized manager
            SocketManager.mark_user_online(current_user.id, "notifications")

            emit(
                "pong",
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "user_id": current_user.id,
                },
            )

        except Exception as e:
            logger.error(f"Notification ping error: {e}")
            emit("error", {"message": "Ping failed"})

    def on_get_notifications(self, data):
        """Handle get notifications request"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Parse pagination parameters
            page = data.get("page", 1)
            per_page = min(data.get("per_page", 20), 50)  # Max 50 per page
            unread_only = data.get("unread_only", False)

            from .services import NotificationService

            notifications = NotificationService.get_user_notifications(
                current_user.id, page=page, per_page=per_page, unread_only=unread_only
            )

            emit(
                "notifications_list",
                {
                    "notifications": notifications["items"],
                    "pagination": notifications["pagination"],
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Error getting notifications: {str(e)}")
            emit("error", {"message": "Failed to get notifications"})

    def on_clear_all_read(self, data):
        """Handle clear all read notifications"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("mark_as_read", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            from .services import NotificationService

            updated = NotificationService.mark_as_read(
                current_user.id
            )  # No IDs = mark all

            emit(
                "clear_all_response",
                {
                    "success": True,
                    "updated": updated,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Error clearing all notifications: {str(e)}")
            emit(
                "clear_all_response",
                {
                    "success": False,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
