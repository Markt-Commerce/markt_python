"""
Centralized event manager for real-time communications
This module provides a clean interface for emitting real-time events with proper error handling
"""
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Union
from external.redis import redis_client
from app.realtime.throttler import event_throttler, redis_event_throttler

# Import removed - using direct task functions instead

logger = logging.getLogger(__name__)


class EventManager:
    """Centralized manager for real-time event emissions"""

    # Event categories for different throttling strategies
    IMMEDIATE_EVENTS = {
        "order_status_changed",
        "new_message",
        "payment_confirmed",
        "delivery_update",
    }

    THROTTLED_EVENTS = {
        "post_liked",
        "post_unliked",
        "comment_reaction_added",
        "comment_reaction_removed",
        "request_upvoted",
        "review_added",
        "review_upvoted",
        "typing_update",
    }

    # Event namespace mapping
    EVENT_NAMESPACES = {
        # Social events
        "post_liked": "/social",
        "post_unliked": "/social",
        "comment_reaction_added": "/social",
        "comment_reaction_removed": "/social",
        "request_upvoted": "/social",
        "review_added": "/social",
        "review_upvoted": "/social",
        "typing_update": "/social",
        # Order events
        "order_status_changed": "/orders",
        "payment_confirmed": "/orders",
        "delivery_update": "/orders",
        # Chat events
        "new_message": "/chat",
        # Notification events
        "notification": "/notification",
    }

    @staticmethod
    def emit_event(
        event: str,
        data: Dict[str, Any],
        room: str,
        namespace: Optional[str] = None,
        use_throttling: bool = True,
        use_async: bool = True,
    ) -> bool:
        """
        Emit a real-time event with proper error handling and optimization

        Args:
            event: Event name
            data: Event data
            room: Target room
            namespace: Socket namespace (optional)
            use_throttling: Whether to apply throttling
            use_async: Whether to use async Celery task

        Returns:
            bool: True if event was queued/emitted successfully
        """
        try:
            # Add timestamp if not present
            if "timestamp" not in data:
                data["timestamp"] = datetime.utcnow().isoformat()

            # Determine emission strategy based on event type
            if event in EventManager.IMMEDIATE_EVENTS:
                # Immediate events - no throttling, direct emission
                return EventManager._emit_immediate(event, data, room, namespace)

            elif event in EventManager.THROTTLED_EVENTS and use_throttling:
                # Throttled events - apply throttling
                return EventManager._emit_throttled(event, data, room, namespace)

            elif use_async:
                # Async events - use Celery tasks
                return EventManager._emit_async(event, data, room, namespace)

            else:
                # Direct emission
                return EventManager._emit_direct(event, data, room, namespace)

        except Exception as e:
            logger.error(f"Failed to emit event {event}: {e}")
            return False

    @staticmethod
    def _emit_immediate(
        event: str, data: Dict[str, Any], room: str, namespace: Optional[str] = None
    ) -> bool:
        """Emit event immediately without throttling"""
        try:
            from main.extensions import socketio

            if namespace:
                socketio.emit(event, data, room=room, namespace=namespace)
            else:
                socketio.emit(event, data, room=room)

            logger.debug(f"Emitted immediate event {event} to room {room}")
            return True

        except Exception as e:
            logger.error(f"Failed to emit immediate event {event}: {e}")
            return False

    @staticmethod
    def _emit_throttled(
        event: str, data: Dict[str, Any], room: str, namespace: Optional[str] = None
    ) -> bool:
        """Emit event with throttling via Celery tasks"""
        try:
            # Throttled events should still use Celery for async processing
            # The throttling happens at the task level, not here
            return EventManager._emit_async(event, data, room, namespace)

        except Exception as e:
            logger.error(f"Failed to emit throttled event {event}: {e}")
            return False

    @staticmethod
    def _emit_async(
        event: str, data: Dict[str, Any], room: str, namespace: Optional[str] = None
    ) -> bool:
        """Emit event asynchronously using Celery"""
        try:
            from app.realtime.tasks import (
                emit_post_liked,
                emit_post_unliked,
                emit_comment_reaction_added,
                emit_comment_reaction_removed,
                emit_buyer_request_upvoted,
                emit_order_status_changed,
                emit_chat_message,
                emit_review_added,
                emit_review_upvoted,
            )

            # Map events to task functions
            task_mapping = {
                "post_liked": emit_post_liked,
                "post_unliked": emit_post_unliked,
                "comment_reaction_added": emit_comment_reaction_added,
                "comment_reaction_removed": emit_comment_reaction_removed,
                "request_upvoted": emit_buyer_request_upvoted,
                "order_status_changed": emit_order_status_changed,
                "new_message": emit_chat_message,
                "review_added": emit_review_added,
                "review_upvoted": emit_review_upvoted,
            }

            task_func = task_mapping.get(event)
            if task_func:
                # Extract parameters from data for task
                if event == "post_liked":
                    task_func(
                        data.get("post_id"),
                        data.get("user_id"),
                        data.get("username"),
                        data.get("like_count"),
                    )
                elif event == "post_unliked":
                    task_func(
                        data.get("post_id"),
                        data.get("user_id"),
                        data.get("username"),
                        data.get("like_count"),
                    )
                elif event == "comment_reaction_added":
                    task_func(
                        data.get("comment_id"),
                        data.get("user_id"),
                        data.get("username"),
                        data.get("reaction_type"),
                    )
                elif event == "comment_reaction_removed":
                    task_func(
                        data.get("comment_id"),
                        data.get("user_id"),
                        data.get("username"),
                        data.get("reaction_type"),
                    )
                elif event == "request_upvoted":
                    task_func(
                        data.get("request_id"),
                        data.get("user_id"),
                        data.get("username"),
                        data.get("upvote_count"),
                    )
                elif event == "order_status_changed":
                    task_func(
                        data.get("order_id"),
                        data.get("user_id"),
                        data.get("status"),
                        data.get("metadata"),
                    )
                elif event == "new_message":
                    task_func(data.get("room_id"), data)
                elif event == "review_added":
                    task_func(data.get("product_id"), data)
                elif event == "review_upvoted":
                    task_func(data.get("product_id"), data)

                logger.debug(f"Queued async event {event} to room {room}")
                return True
            else:
                # Fallback to direct emission
                return EventManager._emit_direct(event, data, room, namespace)

        except Exception as e:
            logger.error(f"Failed to emit async event {event}: {e}")
            return False

    @staticmethod
    def _emit_direct(
        event: str, data: Dict[str, Any], room: str, namespace: Optional[str] = None
    ) -> bool:
        """Emit event directly without any optimization"""
        try:
            from main.extensions import socketio

            if namespace:
                socketio.emit(event, data, room=room, namespace=namespace)
            else:
                socketio.emit(event, data, room=room)

            logger.debug(f"Emitted direct event {event} to room {room}")
            return True

        except Exception as e:
            logger.error(f"Failed to emit direct event {event}: {e}")
            return False

    @staticmethod
    def emit_to_user(
        user_id: str, event: str, data: Dict[str, Any], namespace: Optional[str] = None
    ) -> bool:
        """Emit event to specific user"""
        try:
            room = f"user_{user_id}"
            return EventManager.emit_event(event, data, room, namespace)

        except Exception as e:
            logger.error(f"Failed to emit event to user {user_id}: {e}")
            return False

    @staticmethod
    def emit_to_post(
        post_id: str, event: str, data: Dict[str, Any], namespace: Optional[str] = None
    ) -> bool:
        """Emit event to post room"""
        try:
            room = f"post_{post_id}"
            # Use event-specific namespace if not provided
            if namespace is None:
                namespace = EventManager.EVENT_NAMESPACES.get(event, "/social")
            return EventManager.emit_event(event, data, room, namespace)

        except Exception as e:
            logger.error(f"Failed to emit event to post {post_id}: {e}")
            return False

    @staticmethod
    def emit_to_comment(
        comment_id: Union[int, str],
        event: str,
        data: Dict[str, Any],
        namespace: Optional[str] = None,
    ) -> bool:
        """Emit event to comment room"""
        try:
            room = f"comment_{comment_id}"
            # Use event-specific namespace if not provided
            if namespace is None:
                namespace = EventManager.EVENT_NAMESPACES.get(event, "/social")
            return EventManager.emit_event(event, data, room, namespace)

        except Exception as e:
            logger.error(f"Failed to emit event to comment {comment_id}: {e}")
            return False

    @staticmethod
    def emit_to_request(
        request_id: str,
        event: str,
        data: Dict[str, Any],
        namespace: Optional[str] = None,
    ) -> bool:
        """Emit event to buyer request room"""
        try:
            room = f"request_{request_id}"
            # Use event-specific namespace if not provided
            if namespace is None:
                namespace = EventManager.EVENT_NAMESPACES.get(event, "/social")
            return EventManager.emit_event(event, data, room, namespace)

        except Exception as e:
            logger.error(f"Failed to emit event to request {request_id}: {e}")
            return False

    @staticmethod
    def emit_to_order(
        order_id: str, event: str, data: Dict[str, Any], namespace: Optional[str] = None
    ) -> bool:
        """Emit event to order room"""
        try:
            room = f"order_{order_id}"
            # Use event-specific namespace if not provided
            if namespace is None:
                namespace = EventManager.EVENT_NAMESPACES.get(event, "/orders")
            return EventManager.emit_event(event, data, room, namespace)

        except Exception as e:
            logger.error(f"Failed to emit event to order {order_id}: {e}")
            return False

    @staticmethod
    def emit_to_chat(room_id: str, event: str, data: Dict[str, Any]) -> bool:
        """Emit event to chat room"""
        try:
            room = f"chat_{room_id}"
            return EventManager.emit_event(event, data, room, namespace="/chat")

        except Exception as e:
            logger.error(f"Failed to emit event to chat room {room_id}: {e}")
            return False

    @staticmethod
    def emit_to_product(
        product_id: str,
        event: str,
        data: Dict[str, Any],
        namespace: Optional[str] = None,
    ) -> bool:
        """Emit event to product room"""
        try:
            room = f"product_{product_id}"
            # Use event-specific namespace if not provided
            if namespace is None:
                namespace = EventManager.EVENT_NAMESPACES.get(event, "/social")
            return EventManager.emit_event(event, data, room, namespace)

        except Exception as e:
            logger.error(f"Failed to emit event to product {product_id}: {e}")
            return False

    @staticmethod
    def flush_pending_events() -> Dict[str, int]:
        """Flush all pending throttled events"""
        try:
            return redis_event_throttler.flush_pending_events()
        except Exception as e:
            logger.error(f"Failed to flush pending events: {e}")
            return {}

    @staticmethod
    def get_pending_count() -> int:
        """Get count of pending events"""
        try:
            return redis_event_throttler.get_pending_count()
        except Exception as e:
            logger.error(f"Failed to get pending count: {e}")
            return 0
