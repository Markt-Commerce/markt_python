import logging
from datetime import datetime
from flask_socketio import Namespace, emit, join_room, leave_room
from external.redis import redis_client

logger = logging.getLogger(__name__)


class DeliveryLocationSharing(Namespace):

    def on_join(self, data):
        """Join a delivery location sharing room"""
        room = data.get("room")
        user_id = data.get("user_id")
        join_room(room)
        logger.info(f"User {user_id} joined room {room}")

    def on_leave(self, data):
        """Leave a delivery location sharing room"""
        room = data.get("room")
        user_id = data.get("user_id")
        leave_room(room)
        logger.info(f"User {user_id} left room {room}")

    def on_location_update(self, data):
        """Broadcast updated location to all users in the room"""
        room = data.get("room")
        user_id = data.get("user_id")
        location = data.get("location")
        logger.info(f"User {user_id} updated location in room {room}: {location}")
        emit("location_update", {"user_id": user_id, "location": location}, room=room)