import logging
from datetime import datetime
from flask_socketio import Namespace, emit, join_room, leave_room

logger = logging.getLogger(__name__)


class DeliveryLocationSharing(Namespace):
    """WebSocket namespace for delivery location sharing"""
    
    @staticmethod
    def validate_location_data(data: dict) -> bool:
        """Validate that location data contains required fields"""
        # Note: 'longitude' is the correct spelling (was 'longtitude')
        return (
            data.get("longitude") is not None 
            and data.get("latitude") is not None
        )

    def on_connect(self, auth=None):
        """Handle client connection"""
        logger.info(f"Client connected to delivery namespace: {self.sid}")
        emit("connect_response", {"data": "Connected to delivery location sharing"})

    def on_disconnect(self):
        """Handle client disconnection"""
        logger.info(f"Client disconnected from delivery namespace: {self.sid}")

    def on_join(self, data):
        """Join a delivery location sharing room"""
        try:
            room = data.get("room")
            user_id = data.get("user_id")
            
            if not room or not user_id:
                emit("error", {"message": "Missing room or user_id"})
                return

            #the only user able to join a room is a user associated with the delivery order
            from .services import DeliveryService
            
            found_user = DeliveryService.find_delivery_order_buyer(user_id, room)
            if found_user:
                join_room(room)
                logger.info(f"User {user_id} joined room {room}")
                emit("join_response", {
                    "status": "success",
                    "room": room,
                    "user_id": user_id
                })
            else:
                emit("error", {
                    "message": "User not authorized to join this room.",
                    "room": room
                })
        except Exception as e:
            logger.error(f"Error joining room: {str(e)}")
            emit("error", {
                "message": f"Failed to join room: {str(e)}"
            })

    def on_leave(self, data):
        """Leave a delivery location sharing room"""
        try:
            room = data.get("room")
            user_id = data.get("user_id")
            
            if not room or not user_id:
                emit("error", {"message": "Missing room or user_id"})
                return
                
            leave_room(room)
            logger.info(f"User {user_id} left room {room}")
            emit("leave_response", {
                "status": "success",
                "room": room,
                "user_id": user_id
            })
        except Exception as e:
            logger.error(f"Error leaving room: {str(e)}")
            emit("error", {
                "message": f"Failed to leave room: {str(e)}"
            })
        

    def on_location_update(self, data):
        """Broadcast updated location to all users in the room"""
        try:
            room = data.get("room")
            user_id = data.get("user_id")
            location = data.get("location")
            
            # validate data
            if not room or not user_id:
                emit("error", {"message": "Missing room or user_id"})
                return
                
            if not self.validate_location_data(location):
                emit("error", {
                    "message": "Invalid location data - must include longitude and latitude"
                })
                return

            logger.info(f"User {user_id} updated location in room {room}: {location}")
            
            # Broadcast to all users in the room
            emit("LOCATION_UPDATE", {
                "user_id": user_id,
                "location": location,
                "timestamp": datetime.now().isoformat()
            }, room=room)
            
        except Exception as e:
            logger.error(f"Error sending location update: {str(e)}")
            emit("error", {
                "message": f"Failed to send location update: {str(e)}"
            })