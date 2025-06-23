# python imports
import logging
from typing import Optional, Dict, Any, List
from enum import Enum

# package imports
from sqlalchemy.exc import SQLAlchemyError

# project imports
from external.redis import redis_client
from app.libs.session import session_scope
from app.libs.pagination import Paginator
from app.libs.errors import NotFoundError

# app imports
from .models import Notification, NotificationType

logger = logging.getLogger(__name__)


class DeliveryChannel(Enum):
    WEBSOCKET = "websocket"
    PUSH = "push"
    EMAIL = "email"


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
        NotificationType.PRODUCT_REVIEW: {
            "title": "New Review",
            "message": "{username} reviewed {product_name} with {rating} stars",
        },
        NotificationType.REVIEW_UPVOTE: {
            "title": "Review Upvoted",
            "message": "{username} found your review helpful",
        },
        NotificationType.ORDER_UPDATE: {
            "title": "Order update",
            "message": "Your order #{order_id} status changed to {status}",
        },
        NotificationType.SHIPMENT_UPDATE: {
            "title": "Shipment update",
            "message": "Your shipment for order #{order_id} is {status}",
        },
        NotificationType.PROMOTIONAL: {
            "title": "Special offer",
            "message": "{message}",
        },
        NotificationType.SYSTEM_ALERT: {
            "title": "System notification",
            "message": "{message}",
        },
    }

    # Channel configuration by notification type
    CHANNEL_CONFIG = {
        NotificationType.POST_LIKE: {
            "channels": [DeliveryChannel.WEBSOCKET, DeliveryChannel.PUSH],
            "immediate_websocket": True,
            "push_when_offline": True,
        },
        NotificationType.POST_COMMENT: {
            "channels": [DeliveryChannel.WEBSOCKET, DeliveryChannel.PUSH],
            "immediate_websocket": True,
            "push_when_offline": True,
        },
        NotificationType.NEW_FOLLOWER: {
            "channels": [DeliveryChannel.WEBSOCKET, DeliveryChannel.PUSH],
            "immediate_websocket": True,
            "push_when_offline": True,
        },
        NotificationType.PRODUCT_REVIEW: {
            "channels": [DeliveryChannel.WEBSOCKET, DeliveryChannel.PUSH],
            "immediate_websocket": True,
            "push_when_offline": True,
        },
        NotificationType.REVIEW_UPVOTE: {
            "channels": [DeliveryChannel.WEBSOCKET, DeliveryChannel.PUSH],
            "immediate_websocket": True,
            "push_when_offline": True,
        },
        NotificationType.ORDER_UPDATE: {
            "channels": [
                DeliveryChannel.WEBSOCKET,
                DeliveryChannel.PUSH,
                DeliveryChannel.EMAIL,
            ],
            "immediate_websocket": True,
            "push_when_offline": True,
            "always_email": True,
        },
        NotificationType.SHIPMENT_UPDATE: {
            "channels": [
                DeliveryChannel.WEBSOCKET,
                DeliveryChannel.PUSH,
                DeliveryChannel.EMAIL,
            ],
            "immediate_websocket": True,
            "push_when_offline": True,
            "always_email": True,
        },
        NotificationType.PROMOTIONAL: {
            "channels": [DeliveryChannel.WEBSOCKET, DeliveryChannel.PUSH],
            "immediate_websocket": True,
            "push_when_offline": False,  # Don't spam with promotional push
        },
        NotificationType.SYSTEM_ALERT: {
            "channels": [DeliveryChannel.EMAIL, DeliveryChannel.PUSH],
            "immediate_websocket": False,  # System alerts via reliable channels
            "always_email": True,
            "always_push": True,
        },
    }

    @staticmethod
    def create_notification(
        user_id: str,
        notification_type: NotificationType,
        actor_id: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        metadata_: Optional[Dict[str, Any]] = None,
    ) -> Optional[Notification]:
        """Create notification with intelligent delivery strategy"""
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

            # Format message with safe defaults
            format_data = {
                "username": actor_name or "Someone",
                "product_name": metadata_.get("product_name", "your product")
                if metadata_
                else "your product",
                "rating": metadata_.get("rating", 0) if metadata_ else 0,
                "order_id": reference_id or "N/A",
                "status": metadata_.get("status", "updated")
                if metadata_
                else "updated",
                "message": metadata_.get("message", "") if metadata_ else "",
            }

            message = template["message"].format(**format_data)

            with session_scope() as session:
                notification = Notification(
                    user_id=user_id,
                    type=notification_type,
                    title=template["title"],
                    message=message,
                    is_read=False,
                    is_seen=False,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    metadata_=metadata_ or {},
                )
                session.add(notification)
                session.flush()

                notification_data = notification.to_dict()

                # Hybrid delivery strategy
                delivery_config = NotificationService.CHANNEL_CONFIG.get(
                    notification_type, {}
                )

                # 1. Immediate WebSocket delivery if user is online
                websocket_delivered = False
                if delivery_config.get("immediate_websocket", True):
                    websocket_delivered = (
                        NotificationService._try_immediate_websocket_delivery(
                            user_id, notification_data
                        )
                    )

                # 2. Queue remaining channels for async delivery
                remaining_channels = []
                config_channels = delivery_config.get(
                    "channels", [DeliveryChannel.WEBSOCKET]
                )

                for channel in config_channels:
                    if channel == DeliveryChannel.WEBSOCKET and websocket_delivered:
                        continue  # Already delivered via WebSocket
                    elif channel == DeliveryChannel.PUSH:
                        # Send push if offline OR if always_push is True
                        if (
                            not websocket_delivered
                            and delivery_config.get("push_when_offline", True)
                        ) or delivery_config.get("always_push", False):
                            remaining_channels.append(channel)
                    elif channel == DeliveryChannel.EMAIL:
                        # Send email if always_email is True
                        if delivery_config.get("always_email", False):
                            remaining_channels.append(channel)

                # Queue for async delivery
                if remaining_channels:
                    from .tasks import deliver_notification

                    channel_values = [channel.value for channel in remaining_channels]
                    deliver_notification.delay(notification_data, channel_values)

                logger.info(
                    f"Notification created for user {user_id}, websocket_delivered={websocket_delivered}"
                )
                return notification

        except Exception as e:
            logger.error(f"Notification creation failed: {str(e)}")
            raise

    @staticmethod
    def _try_immediate_websocket_delivery(
        user_id: str, notification_data: Dict
    ) -> bool:
        """Attempt immediate WebSocket delivery, return True if successful"""
        try:
            # Check if user has active connections
            if not redis_client.exists(f"online_users:{user_id}"):
                return False

            # Get all active sessions for this user (handles multiple devices/tabs)
            user_room = f"user_{user_id}"

            from main.extensions import socketio

            # Emit notification
            socketio.emit(
                "notification",
                notification_data,
                room=user_room,
                namespace="/notifications",
            )

            # Update unread count in real-time
            unread_count = NotificationService.get_unread_count(user_id)
            socketio.emit(
                "unread_count_update",
                {"count": unread_count},
                room=user_room,
                namespace="/notifications",
            )

            logger.info(f"Immediate WebSocket delivery successful for user {user_id}")
            return True

        except Exception as e:
            logger.error(
                f"Immediate WebSocket delivery failed for user {user_id}: {str(e)}"
            )
            return False

    @staticmethod
    def get_user_notifications(
        user_id: str, page: int = 1, per_page: int = 20, unread_only: bool = False
    ) -> Dict:
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

                # Mark notifications as seen (appeared in UI)
                if not unread_only:
                    NotificationService._mark_as_seen(
                        session, user_id, [item.id for item in result["items"]]
                    )

                return {
                    "items": [item.to_dict() for item in result["items"]],
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
    def mark_as_read(user_id: str, notification_ids: Optional[List[int]] = None) -> int:
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

                # Emit real-time unread count update
                if updated > 0:
                    from main.extensions import socketio

                    unread_count = NotificationService.get_unread_count(user_id)
                    socketio.emit(
                        "unread_count_update",
                        {"count": unread_count},
                        room=f"user_{user_id}",
                        namespace="/notifications",
                    )

                return updated

        except SQLAlchemyError as e:
            logger.error(f"Error marking notifications as read: {str(e)}")
            raise

    @staticmethod
    def get_unread_count(user_id: str) -> int:
        """Get count of unread notifications"""
        try:
            with session_scope() as session:
                return (
                    session.query(Notification)
                    .filter(
                        Notification.user_id == user_id, Notification.is_read == False
                    )
                    .count()
                )
        except SQLAlchemyError as e:
            logger.error(f"Error getting unread count: {str(e)}")
            return 0

    @staticmethod
    def _mark_as_seen(session, user_id: str, notification_ids: List[int]):
        """Mark notifications as seen (internal helper)"""
        try:
            session.query(Notification).filter(
                Notification.user_id == user_id,
                Notification.id.in_(notification_ids),
                Notification.is_seen == False,
            ).update({"is_seen": True}, synchronize_session=False)
        except Exception as e:
            logger.error(f"Error marking notifications as seen: {str(e)}")
