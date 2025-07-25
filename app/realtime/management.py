"""
Management commands for real-time event system
"""
import logging
from typing import Dict, Any
from app.realtime.throttler import redis_event_throttler
from app.realtime.event_manager import EventManager

logger = logging.getLogger(__name__)


class RealTimeManagement:
    """Management commands for real-time event system"""

    @staticmethod
    def flush_pending_events() -> Dict[str, int]:
        """
        Flush all pending events from Redis

        Returns:
            Dict[str, int]: Count of flushed events by type
        """
        try:
            logger.info("Starting flush of pending events...")
            flushed_counts = redis_event_throttler.flush_pending_events()

            total_flushed = sum(flushed_counts.values())
            logger.info(f"Successfully flushed {total_flushed} pending events")

            # Log breakdown by event type
            for event_type, count in flushed_counts.items():
                logger.info(f"  - {event_type}: {count} events")

            return flushed_counts

        except Exception as e:
            logger.error(f"Failed to flush pending events: {e}")
            return {}

    @staticmethod
    def get_pending_count() -> int:
        """
        Get count of pending events in Redis

        Returns:
            int: Number of pending events
        """
        try:
            count = redis_event_throttler.get_pending_count()
            logger.info(f"Found {count} pending events in Redis")
            return count

        except Exception as e:
            logger.error(f"Failed to get pending count: {e}")
            return 0

    @staticmethod
    def get_pending_events() -> Dict[str, Dict[str, Any]]:
        """
        Get all pending events from Redis

        Returns:
            Dict[str, Dict[str, Any]]: Pending events by key
        """
        try:
            events = redis_event_throttler.get_pending_events()
            logger.info(f"Retrieved {len(events)} pending event keys")
            return events

        except Exception as e:
            logger.error(f"Failed to get pending events: {e}")
            return {}

    @staticmethod
    def force_emit_event(event: str, data: Dict[str, Any], room: str) -> bool:
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
            logger.info(f"Force emitting event {event} to room {room}")
            success = redis_event_throttler.force_emit(event, data, room)

            if success:
                logger.info(f"Successfully force emitted {event}")
            else:
                logger.error(f"Failed to force emit {event}")

            return success

        except Exception as e:
            logger.error(f"Error force emitting event {event}: {e}")
            return False


# Convenience functions for CLI usage
def flush_pending_events():
    """CLI function to flush pending events"""
    return RealTimeManagement.flush_pending_events()


def get_pending_count():
    """CLI function to get pending count"""
    return RealTimeManagement.get_pending_count()


def get_pending_events():
    """CLI function to get pending events"""
    return RealTimeManagement.get_pending_events()


def force_emit_event(event: str, data: Dict[str, Any], room: str):
    """CLI function to force emit event"""
    return RealTimeManagement.force_emit_event(event, data, room)
