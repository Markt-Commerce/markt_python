"""
Event throttler for optimizing real-time event broadcasting
This module implements debouncing and throttling for high-frequency events
"""
import time
import logging
from collections import defaultdict
from typing import Dict, Any, Optional
from external.redis import redis_client

logger = logging.getLogger(__name__)


class EventThrottler:
    """Throttles and batches real-time events for performance optimization"""

    def __init__(self, default_interval: float = 2.0):
        self.default_interval = default_interval
        self.last_emitted = defaultdict(float)
        self.pending_data = defaultdict(dict)

        # Event-specific throttling intervals (in seconds)
        self.event_intervals = {
            "post_liked": 1.0,  # Like counts - moderate throttling
            "post_unliked": 1.0,
            "comment_reaction_added": 0.5,  # Reactions - light throttling
            "comment_reaction_removed": 0.5,
            "request_upvoted": 2.0,  # Upvotes - heavy throttling
            "review_added": 1.0,  # Product reviews - moderate throttling
            "review_upvoted": 1.0,  # Review upvotes - moderate throttling
            "order_status_changed": 0.1,  # Order updates - immediate
            "new_message": 0.1,  # Chat messages - immediate
            "typing_update": 0.5,  # Typing indicators - light throttling
        }

    def throttle_emit(
        self,
        event: str,
        data: Dict[str, Any],
        room: str,
        custom_interval: Optional[float] = None,
    ) -> bool:
        """
        Throttle event emission based on event type and room

        Args:
            event: Event name
            data: Event data
            room: Target room
            custom_interval: Override default interval for this event

        Returns:
            bool: True if event was emitted, False if throttled
        """
        try:
            now = time.time()
            key = f"{event}_{room}"

            # Get interval for this event type
            interval = custom_interval or self.event_intervals.get(
                event, self.default_interval
            )

            # Update pending data (merge with existing data)
            if key in self.pending_data:
                self.pending_data[key].update(data)
            else:
                self.pending_data[key] = data.copy()

            # Check if enough time has passed since last emission
            if now - self.last_emitted[key] >= interval:
                # Emit the accumulated data
                from main.extensions import socketio

                socketio.emit(event, self.pending_data[key], room=room)
                self.last_emitted[key] = now

                # Clear pending data
                del self.pending_data[key]

                logger.debug(f"Emitted throttled event {event} to room {room}")
                return True
            else:
                logger.debug(f"Throttled event {event} to room {room} (pending)")
                return False

        except Exception as e:
            logger.error(f"Error in throttle_emit: {e}")
            return False

    def force_emit(self, event: str, data: Dict[str, Any], room: str) -> bool:
        """
        Force emit an event immediately, bypassing throttling

        Args:
            event: Event name
            data: Event data
            room: Target room

        Returns:
            bool: True if event was emitted successfully
        """
        try:
            from main.extensions import socketio

            # Emit immediately
            socketio.emit(event, data, room=room)

            # Clear any pending data for this event/room
            key = f"{event}_{room}"
            if key in self.pending_data:
                del self.pending_data[key]

            logger.debug(f"Force emitted event {event} to room {room}")
            return True

        except Exception as e:
            logger.error(f"Error in force_emit: {e}")
            return False

    def flush_pending_events(self) -> Dict[str, int]:
        """
        Flush all pending events immediately

        Returns:
            Dict with count of flushed events by type
        """
        try:
            from main.extensions import socketio

            flushed_counts = defaultdict(int)

            for key, data in self.pending_data.items():
                event, room = key.split("_", 1)

                # Emit the pending data
                socketio.emit(event, data, room=room)
                flushed_counts[event] += 1

                logger.debug(f"Flushed pending event {event} to room {room}")

            # Clear all pending data
            self.pending_data.clear()

            logger.info(f"Flushed {sum(flushed_counts.values())} pending events")
            return dict(flushed_counts)

        except Exception as e:
            logger.error(f"Error flushing pending events: {e}")
            return {}

    def get_pending_count(self) -> int:
        """Get count of pending events"""
        return len(self.pending_data)

    def get_pending_events(self) -> Dict[str, Dict[str, Any]]:
        """Get all pending events"""
        return dict(self.pending_data)


class RedisEventThrottler(EventThrottler):
    """Redis-based event throttler for distributed environments"""

    def __init__(self, default_interval: float = 2.0):
        super().__init__(default_interval)

    def throttle_emit(
        self,
        event: str,
        data: Dict[str, Any],
        room: str,
        custom_interval: Optional[float] = None,
    ) -> bool:
        """
        Throttle event emission using Redis for distributed coordination
        """
        try:
            now = time.time()
            key = f"throttle:{event}:{room}"

            # Get interval for this event type
            interval = custom_interval or self.event_intervals.get(
                event, self.default_interval
            )

            # Use Redis to coordinate throttling across multiple instances
            last_emitted = redis_client.get(key)
            if last_emitted:
                last_emitted = float(last_emitted)
            else:
                last_emitted = 0

            # Check if enough time has passed
            if now - last_emitted >= interval:
                # Update last emitted time in Redis
                redis_client.setex(key, int(interval * 2), str(now))

                # Emit the event
                from main.extensions import socketio

                socketio.emit(event, data, room=room)

                logger.debug(f"Emitted throttled event {event} to room {room}")
                return True
            else:
                # Store pending data in Redis for later emission
                pending_key = f"pending:{event}:{room}"
                redis_client.lpush(pending_key, str(data))
                redis_client.expire(pending_key, int(interval * 2))

                logger.debug(
                    f"Throttled event {event} to room {room} (pending in Redis)"
                )
                return False

        except Exception as e:
            logger.error(f"Error in Redis throttle_emit: {e}")
            return False

    def flush_pending_events(self) -> Dict[str, int]:
        """
        Flush all pending events from Redis
        """
        try:
            from main.extensions import socketio

            flushed_counts = defaultdict(int)

            # Get all pending event keys
            pending_keys = redis_client.keys("pending:*")

            for key in pending_keys:
                # Parse event and room from key
                parts = key.split(":")
                if len(parts) >= 3:
                    event = parts[1]
                    room = ":".join(parts[2:])

                    # Get all pending data for this event/room
                    pending_data = redis_client.lrange(key, 0, -1)

                    for data_str in pending_data:
                        try:
                            import json

                            data = json.loads(data_str)

                            # Emit the event
                            socketio.emit(event, data, room=room)
                            flushed_counts[event] += 1

                        except Exception as e:
                            logger.error(f"Error processing pending event data: {e}")

                    # Clear the pending key
                    redis_client.delete(key)

            logger.info(
                f"Flushed {sum(flushed_counts.values())} pending events from Redis"
            )
            return dict(flushed_counts)

        except Exception as e:
            logger.error(f"Error flushing pending events from Redis: {e}")
            return {}


# Global throttler instances
event_throttler = EventThrottler()
redis_event_throttler = RedisEventThrottler()
