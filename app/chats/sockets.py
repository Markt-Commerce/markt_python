import logging
from datetime import datetime
from flask_socketio import Namespace, emit, join_room, leave_room
from external.redis import redis_client
from app.libs.session import session_scope
from .models import ChatRoom, ChatMessage
from .services import ChatService, DiscountService

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
            emit(
                "connected",
                {"status": "connected", "message": "Connected to chat namespace"},
            )
            logger.info("Client connected to chat namespace")

        except Exception as e:
            logger.error(f"Chat connection error: {e}")
            emit("error", {"message": "Connection failed"})

    def on_disconnect(self):
        """Handle client disconnection"""
        from main.sockets import SocketManager

        try:
            logger.info("Client disconnected from chat namespace")
        except Exception as e:
            logger.error(f"Chat disconnection error: {e}")

    # ==================== ROOM MANAGEMENT ====================
    def on_join_room(self, data):
        """Join a chat room with validation"""
        try:
            # Data validation
            is_valid, error_msg = self._validate_data(data, ["room_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")
            user_id = data.get("user_id")  # Expect user_id from client

            # Validate room exists and user has access
            if not ChatService.user_has_access_to_room(user_id, room_id):
                return emit("error", {"message": "Access denied to this room"})

            join_room(f"room_{room_id}")

            # Get room details and recent messages
            try:
                room_data = ChatService.get_room_with_messages(room_id, user_id)
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
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            is_valid, error_msg = self._validate_data(data, ["room_id", "user_id"])
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
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Data validation
            is_valid, error_msg = self._validate_data(
                data, ["room_id", "message", "user_id"]
            )
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")
            message_content = data.get("message")
            message_type =  data.get("message_type")
            product_id = data.get("product_id")

            # Validate room access
            if not ChatService.user_has_access_to_room(user_id, room_id):
                return emit("error", {"message": "Access denied to this room"})
            
            #TODO: message type needs to be check to make sure it falls within the acceptable types

            # Process message through service (includes persistence and validation)
            try:
                message = ChatService.send_message(
                    user_id=user_id,
                    room_id=room_id,
                    content=message_content,
                    message_type=message_type,
                    product_id=product_id,
                )

                # Get sender info for the response
                from app.users.models import User

                with session_scope() as session:
                    sender = session.query(User).filter(User.id == user_id).first()
                    sender_username = sender.username if sender else None

                # Convert ChatMessage to dict for socket emission
                message_data = {
                    "id": message.id,
                    "room_id": message.room_id,
                    "sender_id": message.sender_id,
                    "sender_username": sender_username,
                    "content": message.content,
                    "message_type": message.message_type,
                    "message_data": message.message_data,
                    "is_read": message.is_read,
                    "created_at": message.created_at.isoformat(),
                }

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
                        "message_id": message.id,
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
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Rate limiting
            if not self._check_rate_limit("typing_start", user_id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["room_id", "user_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")

            # Validate room access
            if not ChatService.user_has_access_to_room(user_id, room_id):
                return emit("error", {"message": "Access denied to this room"})

            # Track typing status
            redis_client.hset(
                f"typing:room:{room_id}", user_id, datetime.utcnow().isoformat()
            )
            redis_client.expire(f"typing:room:{room_id}", 10)

            emit(
                "typing_update",
                {
                    "room_id": room_id,
                    "user_id": user_id,
                    "username": data.get(
                        "username", "User"
                    ),  # Fallback or grab from session
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
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Rate limiting
            if not self._check_rate_limit("typing_stop", user_id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["room_id", "user_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")
            redis_client.hdel(f"typing:room:{room_id}", user_id)

            emit(
                "typing_update",
                {
                    "room_id": room_id,
                    "user_id": user_id,
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
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Rate limiting
            if not self._check_rate_limit("message", user_id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(
                data, ["room_id", "product_id", "offer_amount", "user_id"]
            )
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")
            product_id = data.get("product_id")
            offer_amount = data.get("offer_amount")
            message = data.get("message", "")

            # Validate room access
            if not ChatService.user_has_access_to_room(user_id, room_id):
                return emit("error", {"message": "Access denied to this room"})

            # Process offer through service
            try:
                offer_data = ChatService.send_offer(
                    user_id=user_id,
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
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Data validation
            is_valid, error_msg = self._validate_data(
                data, ["offer_id", "response", "user_id"]
            )
            if not is_valid:
                return emit("error", {"message": error_msg})

            offer_id = data.get("offer_id")
            response = data.get("response")  # "accept" or "reject"
            message = data.get("message", "")

            # Process offer response through service
            try:
                response_data = ChatService.respond_to_offer(
                    user_id=user_id,
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
        """Handle ping for connection health check with app-level presence"""
        try:
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Rate limiting
            if not self._check_rate_limit("ping", user_id):
                return emit("error", {"message": "Rate limit exceeded"})

            from main.sockets import SocketManager

            SocketManager.mark_user_online(user_id)

            emit(
                "pong",
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "user_id": user_id,
                },
            )

        except Exception as e:
            logger.error(f"Ping error: {e}")
            emit("error", {"message": "Ping failed"})

    # ==================== MESSAGE REACTIONS ====================
    def on_message_reaction_added(self, data):
        """Handle real-time chat message reaction updates"""
        try:
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Data validation
            is_valid, error_msg = self._validate_data(
                data, ["message_id", "reaction_type", "user_id"]
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
                    "user_id": user_id,
                    "username": data.get("username", "User"),  # Fallback
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
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Data validation
            is_valid, error_msg = self._validate_data(
                data, ["message_id", "reaction_type", "user_id"]
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
                    "user_id": user_id,
                    "username": data.get("username", "User"),  # Fallback
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

    def on_join_message(self, data):
        """Join room for message reaction updates"""
        try:
            user_id = data.get("user_id") if isinstance(data, dict) else None
            message_id = data.get("message_id") if isinstance(data, dict) else data

            if not user_id and not isinstance(data, str):
                return emit("error", {"message": "User ID required"})

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

    def on_leave_message(self, data):
        """Leave message room"""
        try:
            # Handle both string message_id or dict with message_id
            message_id = data.get("message_id") if isinstance(data, dict) else data
            user_id = data.get("user_id") if isinstance(data, dict) else None

            if user_id and message_id:
                leave_room(f"message_{message_id}")
        except Exception as e:
            logger.error(f"Leave message error: {e}")

    # ==================== DISCOUNT EVENTS ====================
    def on_discount_offer(self, data):
        """Handle discount offer creation via websocket (alternative to API)"""
        try:
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Data validation
            required_fields = [
                "room_id",
                "discount_type",
                "discount_value",
                "expires_at",
                "user_id",
            ]
            is_valid, error_msg = self._validate_data(data, required_fields)
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")

            # Validate room access
            if not ChatService.user_has_access_to_room(user_id, room_id):
                return emit("error", {"message": "Access denied to this room"})

            # Create discount offer
            discount = DiscountService.create_discount_offer(
                seller_id=user_id, room_id=room_id, discount_data=data
            )

            # Send confirmation to sender
            emit(
                "discount_offer_created",
                {
                    "discount_id": discount["id"],
                    "message_id": discount["message_id"],
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Discount offer error: {e}")
            emit("error", {"message": "Failed to create discount offer"})

    def on_discount_response(self, data):
        """Handle discount response via websocket"""
        try:
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Data validation
            is_valid, error_msg = self._validate_data(
                data, ["discount_id", "response", "user_id"]
            )
            if not is_valid:
                return emit("error", {"message": error_msg})

            discount_id = data.get("discount_id")
            response = data.get("response")
            response_message = data.get("response_message")

            # Respond to discount
            result = DiscountService.respond_to_discount(
                buyer_id=user_id,
                discount_id=discount_id,
                response=response,
                response_message=response_message,
            )

            # Send confirmation to sender
            emit(
                "discount_response_sent",
                {
                    "discount_id": discount_id,
                    "response": response,
                    "message_id": result["message_id"],
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Discount response error: {e}")
            emit("error", {"message": "Failed to respond to discount"})

    def on_get_discounts(self, data):
        """Get active discounts for a room"""
        try:
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["room_id", "user_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            room_id = data.get("room_id")

            # Validate room access
            if not ChatService.user_has_access_to_room(user_id, room_id):
                return emit("error", {"message": "Access denied to this room"})

            # Get active discounts
            discounts = DiscountService.get_active_discounts_for_user(user_id, room_id)

            # Send discounts data
            emit(
                "discounts_list",
                {
                    "room_id": room_id,
                    "discounts": discounts,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Get discounts error: {e}")
            emit("error", {"message": "Failed to get discounts"})
