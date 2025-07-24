import logging
from datetime import datetime
from typing import Any, Dict, Optional

# package imports
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

# project imports
from external.database import db
from external.redis import redis_client
from app.libs.session import session_scope
from app.libs.errors import (
    NotFoundError,
    ValidationError,
    ForbiddenError,
    APIError,
)

from app.users.models import User, Seller
from app.products.models import Product
from app.requests.models import BuyerRequest

# app imports
from .models import ChatRoom, ChatMessage, ChatOffer, ChatMessageReaction

logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing chat functionality"""

    # Cache keys
    CACHE_KEYS = {
        "user_rooms": "chat:user:{user_id}:rooms",
        "room_messages": "chat:room:{room_id}:messages",
        "typing": "chat:typing:{room_id}:{user_id}",
        "online_status": "chat:online:{user_id}",
        "unread_count": "chat:unread:{user_id}:{room_id}",
    }

    @staticmethod
    def create_or_get_chat_room(
        buyer_id: str,
        seller_id: str,
        product_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> ChatRoom:
        """Create or get existing chat room between buyer and seller"""
        try:
            with session_scope() as session:
                # Check if room already exists
                existing_room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.buyer_id == buyer_id,
                        ChatRoom.seller_id == seller_id,
                        ChatRoom.product_id == product_id,
                        ChatRoom.request_id == request_id,
                    )
                    .first()
                )

                if existing_room:
                    return existing_room

                # Create new room
                room = ChatRoom(
                    buyer_id=buyer_id,
                    seller_id=seller_id,
                    product_id=product_id,
                    request_id=request_id,
                )

                session.add(room)
                session.flush()

                # Cache room for both users
                ChatService._cache_user_room(buyer_id, room)
                ChatService._cache_user_room(seller_id, room)

                return room

        except Exception as e:
            logger.error(f"Failed to create chat room: {str(e)}")
            raise APIError("Failed to create chat room")

    @staticmethod
    def get_user_chat_rooms(
        user_id: str, page: int = 1, per_page: int = 20
    ) -> Dict[str, Any]:
        """Get chat rooms for a user with recent messages"""
        try:
            with session_scope() as session:
                # Get rooms where user is buyer or seller
                rooms = (
                    session.query(ChatRoom)
                    .options(
                        joinedload(ChatRoom.buyer),
                        joinedload(ChatRoom.seller),
                        joinedload(ChatRoom.product),
                        joinedload(ChatRoom.request),
                        joinedload(ChatRoom.messages),
                    )
                    .filter(
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        )
                    )
                    .order_by(ChatRoom.last_message_at.desc())
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                    .all()
                )

                # Enhance rooms with additional data
                enhanced_rooms = []
                for room in rooms:
                    # Get last message
                    last_message = (
                        session.query(ChatMessage)
                        .filter(ChatMessage.room_id == room.id)
                        .order_by(ChatMessage.created_at.desc())
                        .first()
                    )

                    # Get unread count
                    unread_count = ChatService._get_unread_count(room.id, user_id)

                    # Get other user info
                    other_user = room.seller if room.buyer_id == user_id else room.buyer

                    room_data = {
                        "id": room.id,
                        "other_user": {
                            "id": other_user.id,
                            "username": other_user.username,
                            "profile_picture": other_user.profile_picture,
                            "is_seller": hasattr(other_user, "seller_account"),
                        },
                        "product": {
                            "id": room.product.id,
                            "name": room.product.name,
                            "price": float(room.product.price),
                            "image": room.product.media[0].url
                            if room.product.media
                            else None,
                        }
                        if room.product
                        else None,
                        "request": {
                            "id": room.request.id,
                            "title": room.request.title,
                            "description": room.request.description,
                        }
                        if room.request
                        else None,
                        "last_message": {
                            "id": last_message.id,
                            "content": last_message.content,
                            "message_type": last_message.message_type,
                            "sender_id": last_message.sender_id,
                            "created_at": last_message.created_at.isoformat(),
                        }
                        if last_message
                        else None,
                        "unread_count": unread_count,
                        "last_message_at": room.last_message_at.isoformat()
                        if room.last_message_at
                        else None,
                    }

                    enhanced_rooms.append(room_data)

                return {
                    "rooms": enhanced_rooms,
                    "pagination": {
                        "page": page,
                        "per_page": per_page,
                        "total": len(enhanced_rooms),
                    },
                }

        except Exception as e:
            logger.error(f"Failed to get chat rooms: {str(e)}")
            raise APIError("Failed to get chat rooms")

    @staticmethod
    def get_room_messages(
        room_id: int, user_id: str, page: int = 1, per_page: int = 50
    ) -> Dict[str, Any]:
        """Get messages for a specific chat room"""
        try:
            with session_scope() as session:
                # Verify user has access to this room
                room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )

                if not room:
                    raise ForbiddenError("Access denied to this chat room")

                # Get messages with pagination
                messages = (
                    session.query(ChatMessage)
                    .options(joinedload(ChatMessage.sender))
                    .filter(ChatMessage.room_id == room_id)
                    .order_by(ChatMessage.created_at.desc())
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                    .all()
                )

                # Mark messages as read
                ChatService._mark_messages_as_read(room_id, user_id)

                # Format messages
                formatted_messages = []
                for message in reversed(messages):  # Reverse to get chronological order
                    message_data = {
                        "id": message.id,
                        "content": message.content,
                        "message_type": message.message_type,
                        "message_data": message.message_data,
                        "sender": {
                            "id": message.sender.id,
                            "username": message.sender.username,
                            "profile_picture": message.sender.profile_picture,
                        },
                        "is_read": message.is_read,
                        "read_at": message.read_at.isoformat()
                        if message.read_at
                        else None,
                        "created_at": message.created_at.isoformat(),
                    }

                    # Add offer data if message contains an offer
                    if message.message_type == "offer":
                        offer = (
                            session.query(ChatOffer)
                            .filter(ChatOffer.message_id == message.id)
                            .first()
                        )
                        if offer:
                            message_data["offer"] = {
                                "id": offer.id,
                                "product_id": offer.product_id,
                                "price": float(offer.price),
                                "status": offer.status,
                            }

                    formatted_messages.append(message_data)

                return {
                    "messages": formatted_messages,
                    "pagination": {
                        "page": page,
                        "per_page": per_page,
                        "total": len(formatted_messages),
                    },
                }

        except ForbiddenError:
            raise
        except Exception as e:
            logger.error(f"Failed to get room messages: {str(e)}")
            raise APIError("Failed to get messages")

    @staticmethod
    def user_has_access_to_room(user_id: str, room_id: int) -> bool:
        """Check if user has access to a specific chat room"""
        try:
            with session_scope() as session:
                room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )
                return room is not None
        except Exception as e:
            logger.error(f"Failed to check room access: {str(e)}")
            return False

    @staticmethod
    def get_room_with_messages(room_id: int, user_id: str) -> Dict[str, Any]:
        """Get room details with recent messages for socket connection"""
        try:
            with session_scope() as session:
                # Verify user has access to this room
                room = (
                    session.query(ChatRoom)
                    .options(
                        joinedload(ChatRoom.buyer),
                        joinedload(ChatRoom.seller),
                        joinedload(ChatRoom.product),
                        joinedload(ChatRoom.request),
                    )
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )

                if not room:
                    raise ForbiddenError("Access denied to this chat room")

                # Get recent messages (last 50)
                messages = (
                    session.query(ChatMessage)
                    .options(joinedload(ChatMessage.sender))
                    .filter(ChatMessage.room_id == room_id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(50)
                    .all()
                )

                # Get other user info
                other_user = room.seller if room.buyer_id == user_id else room.buyer

                return {
                    "room_id": room.id,
                    "other_user": {
                        "id": other_user.id,
                        "username": other_user.username,
                        "profile_picture": other_user.profile_picture,
                        "is_seller": hasattr(other_user, "seller_account"),
                    },
                    "product": {
                        "id": room.product.id,
                        "name": room.product.name,
                        "price": float(room.product.price),
                        "image": room.product.media[0].url
                        if room.product.media
                        else None,
                    }
                    if room.product
                    else None,
                    "request": {
                        "id": room.request.id,
                        "title": room.request.title,
                        "description": room.request.description,
                    }
                    if room.request
                    else None,
                    "messages": [
                        {
                            "id": msg.id,
                            "content": msg.content,
                            "message_type": msg.message_type,
                            "message_data": msg.message_data,
                            "sender_id": msg.sender_id,
                            "sender_username": msg.sender.username,
                            "is_read": msg.is_read,
                            "created_at": msg.created_at.isoformat(),
                        }
                        for msg in reversed(
                            messages
                        )  # Reverse to get chronological order
                    ],
                    "unread_count": ChatService._get_unread_count(room.id, user_id),
                }

        except Exception as e:
            logger.error(f"Failed to get room with messages: {str(e)}")
            raise APIError("Failed to get room data")

    @staticmethod
    def send_message(
        user_id: str, room_id: int, content: str, product_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a message in a chat room (simplified for socket usage)"""
        try:
            with session_scope() as session:
                # Verify user has access to this room
                room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )

                if not room:
                    raise ForbiddenError("Access denied to this chat room")

                # Create message
                message = ChatMessage(
                    room_id=room_id,
                    sender_id=user_id,
                    content=content,
                    message_type="text",
                    message_data={"product_id": product_id} if product_id else None,
                )

                session.add(message)
                session.flush()

                # Update room's last message timestamp
                room.last_message_at = datetime.utcnow()

                # Update unread counts
                if room.buyer_id == user_id:
                    room.unread_count_seller += 1
                else:
                    room.unread_count_buyer += 1

                session.commit()

                # Get sender info
                sender = session.query(User).filter(User.id == user_id).first()

                return {
                    "id": message.id,
                    "content": message.content,
                    "message_type": message.message_type,
                    "message_data": message.message_data,
                    "sender_id": message.sender_id,
                    "sender_username": sender.username,
                    "is_read": message.is_read,
                    "created_at": message.created_at.isoformat(),
                }

        except Exception as e:
            logger.error(f"Failed to send message: {str(e)}")
            raise APIError("Failed to send message")

    @staticmethod
    def send_offer(
        user_id: str, room_id: int, product_id: str, amount: float, message: str = ""
    ) -> Dict[str, Any]:
        """Send an offer in a chat room"""
        try:
            with session_scope() as session:
                # Verify user has access to this room
                room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )

                if not room:
                    raise ForbiddenError("Access denied to this chat room")

                # Get product details
                product = (
                    session.query(Product).filter(Product.id == product_id).first()
                )
                if not product:
                    raise NotFoundError("Product not found")

                # Create offer message
                message_data = {
                    "product_id": product_id,
                    "product_name": product.name,
                    "product_price": float(product.price),
                    "offer_amount": amount,
                    "offer_message": message,
                }

                chat_message = ChatMessage(
                    room_id=room_id,
                    sender_id=user_id,
                    content=f"Offered ${amount:.2f} for {product.name}",
                    message_type="offer",
                    message_data=message_data,
                )

                session.add(chat_message)
                session.flush()

                # Update room's last message timestamp
                room.last_message_at = datetime.utcnow()

                # Update unread counts
                if room.buyer_id == user_id:
                    room.unread_count_seller += 1
                else:
                    room.unread_count_buyer += 1

                session.commit()

                # Get sender info
                sender = session.query(User).filter(User.id == user_id).first()

                return {
                    "id": chat_message.id,
                    "content": chat_message.content,
                    "message_type": chat_message.message_type,
                    "message_data": chat_message.message_data,
                    "sender_id": chat_message.sender_id,
                    "sender_username": sender.username,
                    "is_read": chat_message.is_read,
                    "created_at": chat_message.created_at.isoformat(),
                }

        except Exception as e:
            logger.error(f"Failed to send offer: {str(e)}")
            raise APIError("Failed to send offer")

    @staticmethod
    def respond_to_offer(offer_id: int, user_id: str, response: str) -> Dict[str, Any]:
        """Respond to a chat offer (accept/reject)"""
        try:
            with session_scope() as session:
                # Get offer
                offer = (
                    session.query(ChatOffer)
                    .join(ChatMessage)
                    .filter(ChatOffer.id == offer_id)
                    .first()
                )

                if not offer:
                    raise NotFoundError("Offer not found")

                # Verify user can respond to this offer
                room = (
                    session.query(ChatRoom)
                    .filter(ChatRoom.id == offer.message.room_id)
                    .first()
                )

                if not room or (room.buyer_id != user_id and room.seller_id != user_id):
                    raise ForbiddenError("Access denied to this offer")

                # Update offer status
                offer.status = response  # "accepted" or "rejected"

                # Create response message
                response_message = ChatMessage(
                    room_id=room.id,
                    sender_id=user_id,
                    content=f"Offer {response}",
                    message_type="offer_response",
                    message_data={"offer_id": offer_id, "response": response},
                )

                session.add(response_message)
                session.flush()

                # Update room
                room.last_message_at = datetime.utcnow()
                session.commit()

                # Send real-time notification
                # ChatSocketManager.send_message_to_room(room.id, {
                #     "type": "offer_response",
                #     "message": {
                #         "id": response_message.id,
                #         "content": response_message.content,
                #         "message_type": "offer_response",
                #         "sender_id": response_message.sender_id,
                #         "created_at": response_message.created_at.isoformat(),
                #         "offer_response": {
                #             "offer_id": offer_id,
                #             "response": response,
                #         }
                #     }
                # })

                return {
                    "offer_id": offer_id,
                    "status": response,
                    "message": response_message,
                }

        except (ForbiddenError, NotFoundError):
            raise
        except Exception as e:
            logger.error(f"Failed to respond to offer: {str(e)}")
            raise APIError("Failed to respond to offer")

    @staticmethod
    def mark_messages_as_read(room_id: int, user_id: str) -> bool:
        """Mark all messages in a room as read for a user"""
        try:
            with session_scope() as session:
                # Verify user has access to this room
                room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )

                if not room:
                    raise ForbiddenError("Access denied to this chat room")

                # Mark messages as read
                unread_messages = (
                    session.query(ChatMessage)
                    .filter(
                        ChatMessage.room_id == room_id,
                        ChatMessage.sender_id != user_id,
                        ChatMessage.is_read == False,
                    )
                    .all()
                )

                for message in unread_messages:
                    message.is_read = True
                    message.read_at = datetime.utcnow()

                # Reset unread count
                if room.buyer_id == user_id:
                    room.unread_count_buyer = 0
                else:
                    room.unread_count_seller = 0

                session.commit()

                return True

        except ForbiddenError:
            raise
        except Exception as e:
            logger.error(f"Failed to mark messages as read: {str(e)}")
            raise APIError("Failed to mark messages as read")

    @staticmethod
    def set_typing_status(room_id: int, user_id: str, is_typing: bool) -> bool:
        """Set typing status for a user in a room"""
        try:
            # Verify user has access to this room
            with session_scope() as session:
                room = (
                    session.query(ChatRoom)
                    .filter(
                        ChatRoom.id == room_id,
                        db.or_(
                            ChatRoom.buyer_id == user_id,
                            ChatRoom.seller_id == user_id,
                        ),
                    )
                    .first()
                )

                if not room:
                    raise ForbiddenError("Access denied to this chat room")

            # Set typing status in Redis
            cache_key = ChatService.CACHE_KEYS["typing"].format(
                room_id=room_id, user_id=user_id
            )

            if is_typing:
                redis_client.setex(cache_key, 30, "typing")  # 30 seconds timeout
            else:
                redis_client.delete(cache_key)

            # Send real-time notification
            # ChatSocketManager.send_message_to_room(room_id, {
            #     "type": "typing_status",
            #     "user_id": user_id,
            #     "is_typing": is_typing,
            # })

            return True

        except ForbiddenError:
            raise
        except Exception as e:
            logger.error(f"Failed to set typing status: {str(e)}")
            raise APIError("Failed to set typing status")

    @staticmethod
    def set_online_status(user_id: str, is_online: bool) -> bool:
        """Set user's online status"""
        try:
            cache_key = ChatService.CACHE_KEYS["online_status"].format(user_id=user_id)

            if is_online:
                redis_client.setex(cache_key, 300, "online")  # 5 minutes timeout
            else:
                redis_client.delete(cache_key)

            return True

        except Exception as e:
            logger.error(f"Failed to set online status: {str(e)}")
            return False

    @staticmethod
    def get_online_status(user_id: str) -> bool:
        """Get user's online status"""
        try:
            cache_key = ChatService.CACHE_KEYS["online_status"].format(user_id=user_id)
            return redis_client.exists(cache_key) > 0
        except Exception as e:
            logger.error(f"Failed to get online status: {str(e)}")
            return False

    # Helper methods
    @staticmethod
    def _cache_user_room(user_id: str, room: ChatRoom):
        """Cache room for user"""
        try:
            cache_key = ChatService.CACHE_KEYS["user_rooms"].format(user_id=user_id)
            # This would cache the room data
        except Exception as e:
            logger.warning(f"Failed to cache user room: {str(e)}")

    @staticmethod
    def _get_unread_count(room_id: int, user_id: str) -> int:
        """Get unread message count for user in room"""
        try:
            with session_scope() as session:
                count = (
                    session.query(ChatMessage)
                    .filter(
                        ChatMessage.room_id == room_id,
                        ChatMessage.sender_id != user_id,
                        ChatMessage.is_read == False,
                    )
                    .count()
                )
                return count
        except Exception as e:
            logger.error(f"Failed to get unread count: {str(e)}")
            return 0

    @staticmethod
    def _mark_messages_as_read(room_id: int, user_id: str):
        """Mark messages as read for user in room"""
        try:
            with session_scope() as session:
                (
                    session.query(ChatMessage)
                    .filter(
                        ChatMessage.room_id == room_id,
                        ChatMessage.sender_id != user_id,
                        ChatMessage.is_read == False,
                    )
                    .update(
                        {
                            "is_read": True,
                            "read_at": datetime.utcnow(),
                        }
                    )
                )
                session.commit()
        except Exception as e:
            logger.error(f"Failed to mark messages as read: {str(e)}")


class ChatReactionService:
    """Service for managing reactions on chat messages"""

    @staticmethod
    def add_message_reaction(user_id: str, message_id: int, reaction_type: str):
        """Add or update a reaction on a chat message"""
        try:
            with session_scope() as session:
                # Check if message exists
                message = session.query(ChatMessage).get(message_id)
                if not message:
                    raise NotFoundError("Message not found")

                # Check if user already has this reaction
                existing_reaction = (
                    session.query(ChatMessageReaction)
                    .filter_by(
                        message_id=message_id,
                        user_id=user_id,
                        reaction_type=reaction_type,
                    )
                    .first()
                )

                if existing_reaction:
                    # User already has this reaction, return existing
                    return existing_reaction

                # Create new reaction
                reaction = ChatMessageReaction(
                    message_id=message_id, user_id=user_id, reaction_type=reaction_type
                )
                session.add(reaction)
                session.commit()

                # Emit real-time websocket event
                try:
                    from flask_socketio import emit

                    emit(
                        "message_reaction_added",
                        {
                            "message_id": message_id,
                            "user_id": user_id,
                            "reaction_type": reaction_type,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                        room=f"message_{message_id}",
                    )
                except Exception as e:
                    logger.warning(f"Failed to emit message_reaction_added event: {e}")

                return reaction

        except Exception as e:
            logger.error(f"Failed to add message reaction: {str(e)}")
            raise APIError("Failed to add reaction")

    @staticmethod
    def remove_message_reaction(user_id: str, message_id: int, reaction_type: str):
        """Remove a reaction from a chat message"""
        try:
            with session_scope() as session:
                reaction = (
                    session.query(ChatMessageReaction)
                    .filter_by(
                        message_id=message_id,
                        user_id=user_id,
                        reaction_type=reaction_type,
                    )
                    .first()
                )

                if not reaction:
                    raise NotFoundError("Reaction not found")

                session.delete(reaction)
                session.commit()

                # Emit real-time websocket event
                try:
                    from flask_socketio import emit

                    emit(
                        "message_reaction_removed",
                        {
                            "message_id": message_id,
                            "user_id": user_id,
                            "reaction_type": reaction_type,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                        room=f"message_{message_id}",
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to emit message_reaction_removed event: {e}"
                    )

                return True

        except Exception as e:
            logger.error(f"Failed to remove message reaction: {str(e)}")
            raise APIError("Failed to remove reaction")

    @staticmethod
    def get_message_reactions(message_id: int, user_id: str = None):
        """Get all reactions for a chat message with counts and user's reactions"""
        try:
            with session_scope() as session:
                # Get all reactions for the message
                reactions = (
                    session.query(ChatMessageReaction)
                    .filter_by(message_id=message_id)
                    .all()
                )

                # Group by reaction type and count
                reaction_counts = {}
                user_reactions = set()

                for reaction in reactions:
                    reaction_type = reaction.reaction_type.value
                    reaction_counts[reaction_type] = (
                        reaction_counts.get(reaction_type, 0) + 1
                    )

                    if user_id and reaction.user_id == user_id:
                        user_reactions.add(reaction_type)

                # Format response
                result = []
                for reaction_type, count in reaction_counts.items():
                    result.append(
                        {
                            "reaction_type": reaction_type,
                            "count": count,
                            "has_reacted": reaction_type in user_reactions,
                        }
                    )

                return result

        except Exception as e:
            logger.error(f"Failed to get message reactions: {str(e)}")
            raise APIError("Failed to get reactions")
