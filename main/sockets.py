import logging
from flask_socketio import emit, disconnect
from app.socials.sockets import SocialNamespace
from app.notifications.sockets import NotificationNamespace
from app.orders.sockets import OrderNamespace
from app.chats.sockets import ChatNamespace

logger = logging.getLogger(__name__)


class SocketManager:
    """Centralized socket connection manager"""

    @staticmethod
    def is_user_online(user_id: str) -> bool:
        """Check if user is online across all namespaces"""
        from external.redis import redis_client

        return redis_client.exists(f"user_online:{user_id}") == 1

    @staticmethod
    def mark_user_online(user_id: str, namespace: str = "general"):
        """Mark user as online with namespace context"""
        from external.redis import redis_client

        redis_client.set(f"user_online:{user_id}", namespace, ex=300)
        redis_client.sadd("online_users", user_id)

    @staticmethod
    def mark_user_offline(user_id: str):
        """Mark user as offline"""
        from external.redis import redis_client

        redis_client.delete(f"user_online:{user_id}")
        redis_client.srem("online_users", user_id)

    @staticmethod
    def get_online_users() -> list:
        """Get list of online users"""
        from external.redis import redis_client

        return list(redis_client.smembers("online_users"))


def register_socket_namespaces(socketio):
    """Register socket namespaces with enhanced architecture

    Architecture Decision:
    - Server-side emissions for critical real-time features
    - Client-side events for non-critical updates
    - Hybrid approach for notifications (immediate + fallback)
    - Centralized connection management
    - Rate limiting and error recovery

    Namespace Structure:
    /social - Social interactions (server-side emissions)
    /notification - Notifications (hybrid approach)
    /orders - Order tracking and payment updates (server-side emissions)
    /chat - Real-time messaging with server-side persistence
    """

    # Register namespaces with error handling
    try:
        socketio.on_namespace(SocialNamespace("/social"))
        socketio.on_namespace(NotificationNamespace("/notification"))
        socketio.on_namespace(OrderNamespace("/orders"))
        # socketio.on_namespace(ChatNamespace("/chat"))

        # Add global error handler for socket connections
        @socketio.on_error()
        def error_handler(e):
            logger.error(f"SocketIO error: {e}")
            # Emit error to client if possible
            try:
                emit("error", {"message": "Connection error occurred"})
            except:
                pass

        # Add connection event logging with enhanced management
        @socketio.on("connect")
        def handle_connect():
            logger.info("Client connected")
            # Track connection metrics
            from external.redis import redis_client

            redis_client.incr("socket_connections")
            redis_client.incr("socket_connections_total")

        @socketio.on("disconnect")
        def handle_disconnect():
            logger.info("Client disconnected")
            # Update connection metrics
            from external.redis import redis_client

            redis_client.decr("socket_connections")

        # Add heartbeat mechanism
        @socketio.on("ping")
        def handle_ping(data):
            """Handle client ping for connection health"""
            try:
                emit("pong", {"timestamp": data.get("timestamp")})
            except Exception as e:
                logger.error(f"Ping error: {e}")

    except Exception as e:
        logger.error(f"Error registering socket namespaces: {e}")
        raise


def emit_to_user(user_id: str, event: str, data: dict, namespace: str = None):
    """Centralized method to emit events to specific user"""
    try:
        from main.extensions import socketio

        room = f"user_{user_id}"

        if namespace:
            socketio.emit(event, data, room=room, namespace=namespace)
        else:
            socketio.emit(event, data, room=room)

        logger.debug(f"Emitted {event} to user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to emit {event} to user {user_id}: {e}")
        return False


def emit_to_room(room: str, event: str, data: dict, namespace: str = None):
    """Centralized method to emit events to specific room"""
    try:
        from main.extensions import socketio

        if namespace:
            socketio.emit(event, data, room=room, namespace=namespace)
        else:
            socketio.emit(event, data, room=room)

        logger.debug(f"Emitted {event} to room {room}")
        return True
    except Exception as e:
        logger.error(f"Failed to emit {event} to room {room}: {e}")
        return False
