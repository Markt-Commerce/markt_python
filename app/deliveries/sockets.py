import logging
from datetime import datetime
from flask_socketio import Namespace, emit, join_room, leave_room
from external.redis import redis_client

from .services import DeliveryService

logger = logging.getLogger(__name__)


class DeliveryLocationSharing(Namespace):

    def validate_location_data(data: dict) -> bool:
        #it should at least contain longtitude and latitude
        return data["longtitude"] and data["latitude"]

    def on_join(self, data):
        """Join a delivery location sharing room"""
        try:
            room = data.get("room")
            user_id = data.get("user_id")
            if room and user_id:
                #the only user able to join a room is a user 
                #TODO: 
                DeliveryService.find_delivery_order_buyer(user_id, room) #check if the user is part of the delivery order, this is for security purposes
                join_room(room)
                logger.info(f"User {user_id} joined room {room}")
        except Exception as e:
            emit("error", "cannot join room. {e}")
            logger.error("could not join room. Reason: {e}")
        

    def on_leave(self, data):
        """Leave a delivery location sharing room"""
        try:
            room = data.get("room")
            user_id = data.get("user_id")
            if room and user_id:
                leave_room(room)
                logger.info(f"User {user_id} left room {room}")
        except Exception as e:
            emit("error", "cannot leave room. {e}")
            logger.error("could not leave room. Reason: {e}")
        

    def on_location_update(self, data):
        """Broadcast updated location to all users in the room"""
        try:
            room = data.get("room")
            user_id = data.get("user_id")
            location = data.get("location")
            # validate data
            if room and user_id and self.validate_location_data():
                logger.info(f"User {user_id} updated location in room {room}: {location}")
                emit("location_update", {"user_id": user_id, "location": location}, room=room)
        except Exception as e:
            logger.error("cannot send location update. Reason {e}")