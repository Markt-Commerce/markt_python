import logging
from datetime import datetime
from flask_socketio import Namespace, emit, join_room, leave_room
from flask_login import current_user
from external.redis import redis_client
from app.libs.session import session_scope
from .models import ChatRoom, ChatMessage
from .services import ChatService

logger = logging.getLogger(__name__)


class ChatNamespace(Namespace):
    """Enhanced chat namespace with server-side message handling and persistence"""

    # Rate limiting configuration
    RATE_LIMITS = {
        "message": {"max_calls": 30, "window": 60},  # 30 messages per minute
        "typing_start": {"max_calls": 10, "window": 60},
        "typing_stop": {"max_calls": 10, "window": 60},
        "ping": {"max_calls": 30, "window": 60},
    }

    def _check_rate_limit(self, event_type: str, user_id: str) -> bool:
        """Check if user has exceeded rate limit for event type"""
        try:
            key = f"rate_limit:chat:{event_type}:{user_id}"
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
        """Handle client connection for chat features"""
        from main.sockets import SocketManager

        try:
            if not current_user.is_authenticated:
                logger.warning("Unauthorized chat connection attempt")
                return emit("error", {"message": "Unauthorized"})

            # Join user-specific room
            join_room(f"user_{current_user.id}")

            # Mark user as online using centralized manager
            SocketManager.mark_user_online(current_user.id, "chat")

            emit("connected", {"status": "connected", "user_id": current_user.id})
            logger.info(f"User {current_user.id} connected to chat namespace")

        except Exception as e:
            logger.error(f"Chat connection error: {e}")
            emit("error", {"message": "Connection failed"})

    def on_disconnect(self):
        """Handle client disconnection"""
        from main.sockets import SocketManager

        try:
            if current_user.is_authenticated:
                leave_room(f"user_{current_user.id}")
                SocketManager.mark_user_offline(current_user.id)
                logger.info(f"User {current_user.id} disconnected from chat namespace")
        except Exception as e:
            logger.error(f"Chat disconnection error: {e}")

    # ==================== ROOM MANAGEMENT ====================
    def on_join_room(self, data):
        """Join a chat room with validation"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("message", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["room_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")

            # Validate room exists and user has access
            if not ChatService.user_has_access_to_room(current_user.id, room_id):
                return emit("error", {"message": "Access denied to this room"})

            join_room(f"room_{room_id}")

            # Get room details and recent messages
            try:
                room_data = ChatService.get_room_with_messages(room_id, current_user.id)
                emit(
                    "room_joined",
                    {
                        "room_id": room_id,
                        "room_data": room_data,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
            except Exception as e:
                logger.error(f"Error getting room data: {str(e)}")
                emit("error", {"message": "Failed to get room data"})

        except Exception as e:
            logger.error(f"Join room error: {e}")
            emit("error", {"message": "Failed to join room"})

    def on_leave_room(self, data):
        """Leave a chat room"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            is_valid, error_msg = self._validate_data(data, ["room_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")
            leave_room(f"room_{room_id}")

            emit(
                "room_left",
                {
                    "room_id": room_id,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Leave room error: {e}")
            emit("error", {"message": "Failed to leave room"})

    # ==================== MESSAGE HANDLING ====================
    def on_message(self, data):
        """Handle incoming message with server-side processing"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("message", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["room_id", "message"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")
            message_content = data.get("message")
            product_id = data.get("product_id")

            # Validate room access
            if not ChatService.user_has_access_to_room(current_user.id, room_id):
                return emit("error", {"message": "Access denied to this room"})

            # Process message through service (includes persistence and validation)
            try:
                message_data = ChatService.send_message(
                    user_id=current_user.id,
                    room_id=room_id,
                    content=message_content,
                    product_id=product_id,
                )

                # Emit to all users in the room (server-side emission)
                emit(
                    "message",
                    message_data,
                    to=f"room_{room_id}",
                    include_self=False,  # Don't send back to sender
                )

                # Send confirmation to sender
                emit(
                    "message_sent",
                    {
                        "message_id": message_data["id"],
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )

            except Exception as e:
                logger.error(f"Error sending message: {str(e)}")
                emit("error", {"message": "Failed to send message"})

        except Exception as e:
            logger.error(f"Message error: {e}")
            emit("error", {"message": "Failed to process message"})

    # ==================== TYPING INDICATORS ====================
    def on_typing_start(self, data):
        """Handle typing start indicator"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("typing_start", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["room_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")

            # Validate room access
            if not ChatService.user_has_access_to_room(current_user.id, room_id):
                return emit("error", {"message": "Access denied to this room"})

            # Track typing status
            redis_client.hset(
                f"typing:room:{room_id}", current_user.id, datetime.utcnow().isoformat()
            )
            redis_client.expire(f"typing:room:{room_id}", 10)

            emit(
                "typing_update",
                {
                    "room_id": room_id,
                    "user_id": current_user.id,
                    "username": current_user.username,
                    "action": "start",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                to=f"room_{room_id}",
                include_self=False,
            )

        except Exception as e:
            logger.error(f"Typing start error: {e}")
            emit("error", {"message": "Failed to process typing start"})

    def on_typing_stop(self, data):
        """Handle typing stop indicator"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("typing_stop", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["room_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")
            redis_client.hdel(f"typing:room:{room_id}", current_user.id)

            emit(
                "typing_update",
                {
                    "room_id": room_id,
                    "user_id": current_user.id,
                    "action": "stop",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                to=f"room_{room_id}",
                include_self=False,
            )

        except Exception as e:
            logger.error(f"Typing stop error: {e}")
            emit("error", {"message": "Failed to process typing stop"})

    # ==================== OFFER HANDLING ====================
    def on_send_offer(self, data):
        """Handle offer creation and sending"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("message", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(
                data, ["room_id", "product_id", "offer_amount"]
            )
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")
            product_id = data.get("product_id")
            offer_amount = data.get("offer_amount")
            message = data.get("message", "")

            # Validate room access
            if not ChatService.user_has_access_to_room(current_user.id, room_id):
                return emit("error", {"message": "Access denied to this room"})

            # Process offer through service
            try:
                offer_data = ChatService.send_offer(
                    user_id=current_user.id,
                    room_id=room_id,
                    product_id=product_id,
                    amount=offer_amount,
                    message=message,
                )

                # Emit to all users in the room
                emit(
                    "offer_sent",
                    offer_data,
                    to=f"room_{room_id}",
                    include_self=False,
                )

                # Send confirmation to sender
                emit(
                    "offer_confirmed",
                    {
                        "offer_id": offer_data["id"],
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )

            except Exception as e:
                logger.error(f"Error sending offer: {str(e)}")
                emit("error", {"message": "Failed to send offer"})

        except Exception as e:
            logger.error(f"Offer error: {e}")
            emit("error", {"message": "Failed to process offer"})

    def on_respond_to_offer(self, data):
        """Handle offer response (accept/reject)"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["offer_id", "response"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            offer_id = data.get("offer_id")
            response = data.get("response")  # "accept" or "reject"
            message = data.get("message", "")

            # Process offer response through service
            try:
                response_data = ChatService.respond_to_offer(
                    user_id=current_user.id,
                    offer_id=offer_id,
                    response=response,
                    message=message,
                )

                # Emit to all users in the room
                room_id = response_data["room_id"]
                emit(
                    "offer_response",
                    response_data,
                    to=f"room_{room_id}",
                )

            except Exception as e:
                logger.error(f"Error responding to offer: {str(e)}")
                emit("error", {"message": "Failed to respond to offer"})

        except Exception as e:
            logger.error(f"Offer response error: {e}")
            emit("error", {"message": "Failed to process offer response"})

    # ==================== UTILITY ====================
    def on_ping(self, data):
        """Handle ping for connection health check"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("ping", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            emit(
                "pong",
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "user_id": current_user.id,
                },
            )

        except Exception as e:
            logger.error(f"Ping error: {e}")
            emit("error", {"message": "Ping failed"})

    # ==================== MESSAGE REACTIONS ====================
    def on_message_reaction_added(self, data):
        """Handle real-time chat message reaction updates"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Data validation
            is_valid, error_msg = self._validate_data(
                data, ["message_id", "reaction_type"]
            )
            if not is_valid:
                return emit("error", {"message": error_msg})

            message_id = data.get("message_id")
            reaction_type = data.get("reaction_type")

            # Emit reaction event to room
            emit(
                "message_reaction_added",
                {
                    "message_id": message_id,
                    "user_id": current_user.id,
                    "username": current_user.username,
                    "reaction_type": reaction_type,
                    "timestamp": datetime.utcnow().isoformat(),
                },
                room=f"message_{message_id}",
            )

            # Update Redis cache
            redis_client.hincrby(f"message:{message_id}:reactions", reaction_type, 1)

        except Exception as e:
            logger.error(f"Message reaction error: {e}")
            emit("error", {"message": "Reaction failed"})

    def on_message_reaction_removed(self, data):
        """Handle real-time chat message reaction removal"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Data validation
            is_valid, error_msg = self._validate_data(
                data, ["message_id", "reaction_type"]
            )
            if not is_valid:
                return emit("error", {"message": error_msg})

            message_id = data.get("message_id")
            reaction_type = data.get("reaction_type")

            # Emit reaction removal event
            emit(
                "message_reaction_removed",
                {
                    "message_id": message_id,
                    "user_id": current_user.id,
                    "username": current_user.username,
                    "reaction_type": reaction_type,
                    "timestamp": datetime.utcnow().isoformat(),
                },
                room=f"message_{message_id}",
            )

            # Update Redis cache
            redis_client.hincrby(f"message:{message_id}:reactions", reaction_type, -1)

        except Exception as e:
            logger.error(f"Message reaction removal error: {e}")
            emit("error", {"message": "Reaction removal failed"})

    def on_join_message(self, message_id):
        """Join room for message reaction updates"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            if not message_id:
                return emit("error", {"message": "Message ID required"})

            join_room(f"message_{message_id}")

            # Get real-time reaction stats
            reactions = redis_client.hgetall(f"message:{message_id}:reactions")
            reaction_stats = {k.decode(): int(v) for k, v in reactions.items()}

            emit(
                "message_reaction_stats",
                {
                    "message_id": message_id,
                    "reactions": reaction_stats,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Join message error: {e}")
            emit("error", {"message": "Failed to join message"})

    def on_leave_message(self, message_id):
        """Leave message room"""
        try:
            if current_user.is_authenticated and message_id:
                leave_room(f"message_{message_id}")
        except Exception as e:
            logger.error(f"Leave message error: {e}")
