"""
Delivery location sharing namespace.

Auth: Connections must be authenticated via Flask-Login (session cookie).
User identity is taken from the server session, not from client payloads.
- Buyers (User): can join rooms for orders they bought; user_id = User.id.
- Delivery partners (DeliveryUser): can send location updates for rooms they are assigned to.
"""
import logging
from datetime import datetime
from flask import request
from flask_login import current_user
from flask_socketio import Namespace, emit, join_room, leave_room

logger = logging.getLogger(__name__)

# Server-side identity per socket: sid -> {user_id, role}
# role is "buyer" (marketplace User) or "delivery_partner" (DeliveryUser)
_delivery_socket_users = {}


def _get_socket_user():
    """Return {user_id, role} for the current request.sid, or None if not authenticated for this socket."""
    sid = getattr(request, "sid", None)
    if not sid:
        return None
    return _delivery_socket_users.get(sid)


def _role_for_user(user):
    """Return 'buyer' for User, 'delivery_partner' for DeliveryUser, else None."""
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
        or not user.is_authenticated
    ):
        return None
    cls_name = type(user).__name__
    if cls_name == "User":
        return "buyer"
    if cls_name == "DeliveryUser":
        return "delivery_partner"
    return None


class DeliveryLocationSharing(Namespace):
    """WebSocket namespace for delivery location sharing. Auth via session."""

    @staticmethod
    def validate_location_data(data: dict) -> bool:
        """Validate that location data contains required fields."""
        return (
            data is not None
            and data.get("longitude") is not None
            and data.get("latitude") is not None
        )

    def on_connect(self, auth=None):
        """Require authenticated session. Reject unauthenticated connections."""
        sid = getattr(request, "sid", None)
        if not sid:
            emit("error", {"message": "Connection error"})
            return False

        if not current_user.is_authenticated:
            logger.warning(
                "Delivery namespace: connection rejected (not authenticated)"
            )
            emit(
                "error",
                {
                    "message": "Authentication required. Connect with session credentials."
                },
            )
            return False

        role = _role_for_user(current_user)
        if role not in ("buyer", "delivery_partner"):
            emit("error", {"message": "Invalid account type for delivery tracking."})
            return False

        _delivery_socket_users[sid] = {
            "user_id": current_user.id,
            "role": role,
        }
        logger.info(f"Delivery namespace: {role} connected sid={sid}")
        emit(
            "connect_response",
            {"data": "Connected to delivery location sharing", "role": role},
        )
        return True

    def on_disconnect(self):
        """Clear server-side identity for this socket."""
        sid = getattr(request, "sid", None)
        if sid and sid in _delivery_socket_users:
            del _delivery_socket_users[sid]
        logger.info(f"Client disconnected from delivery namespace: {sid}")

    def on_join(self, data):
        """Join a delivery location room. Only buyers; user_id is taken from session."""
        try:
            info = _get_socket_user()
            if not info:
                emit("error", {"message": "Not authenticated"})
                return
            if info["role"] != "buyer":
                emit(
                    "error",
                    {
                        "message": "Only buyers can join a delivery room to track location."
                    },
                )
                return

            room = (data or {}).get("room")
            if not room:
                emit("error", {"message": "Missing room"})
                return

            from .services import DeliveryService

            user_id = info["user_id"]
            if not DeliveryService.find_delivery_order_buyer(user_id, room):
                emit(
                    "error",
                    {"message": "Not authorized to join this room.", "room": room},
                )
                return

            join_room(room)
            logger.info(f"Buyer {user_id} joined room {room}")
            emit(
                "join_response", {"status": "success", "room": room, "user_id": user_id}
            )
        except Exception as e:
            logger.error(f"Error joining room: {e}", exc_info=True)
            emit("error", {"message": "Failed to join room"})

    def on_leave(self, data):
        """Leave a delivery room. Identity from session."""
        try:
            info = _get_socket_user()
            if not info:
                emit("error", {"message": "Not authenticated"})
                return

            room = (data or {}).get("room")
            if not room:
                emit("error", {"message": "Missing room"})
                return

            leave_room(room)
            logger.info(f"User {info['user_id']} left room {room}")
            emit(
                "leave_response",
                {"status": "success", "room": room, "user_id": info["user_id"]},
            )
        except Exception as e:
            logger.error(f"Error leaving room: {e}", exc_info=True)
            emit("error", {"message": "Failed to leave room"})

    def on_location_update(self, data):
        """Broadcast location to room. Only delivery partners assigned to this room."""
        try:
            info = _get_socket_user()
            if not info:
                emit("error", {"message": "Not authenticated"})
                return
            if info["role"] != "delivery_partner":
                emit(
                    "error",
                    {"message": "Only delivery partners can send location updates."},
                )
                return

            room = (data or {}).get("room")
            location = (data or {}).get("location")
            if not room:
                emit("error", {"message": "Missing room"})
                return
            if not self.validate_location_data(location):
                emit(
                    "error",
                    {"message": "Invalid location: longitude and latitude required."},
                )
                return

            from .services import DeliveryService

            if not DeliveryService.is_delivery_partner_for_room(info["user_id"], room):
                emit(
                    "error",
                    {
                        "message": "Not authorized to send location for this room.",
                        "room": room,
                    },
                )
                return

            # Use server-known identity, not client payload
            emit(
                "LOCATION_UPDATE",
                {
                    "user_id": info["user_id"],
                    "location": location,
                    "timestamp": datetime.utcnow().isoformat(),
                },
                room=room,
            )
            logger.debug(f"Location update from {info['user_id']} in room {room}")
        except Exception as e:
            logger.error(f"Error sending location update: {e}", exc_info=True)
            emit("error", {"message": "Failed to send location update"})
