# package imports
import logging
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)

# project imports
from app.libs.schemas import PaginationQueryArgs
from app.libs.decorators import dual_role_required
from app.libs.errors import APIError

# app imports
from .schemas import (
    ChatRoomSchema,
    ChatMessageSchema,
    ChatRoomListSchema,
    ChatMessageListSchema,
    CreateChatRoomSchema,
    SendMessageSchema,
)
from .services import ChatService

bp = Blueprint("chats", __name__, description="Chat operations", url_prefix="/chats")


@bp.route("/rooms")
class ChatRooms(MethodView):
    @login_required
    # @dual_role_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, ChatRoomListSchema)
    def get(self, args):
        """Get user's chat rooms"""
        try:
            page = args.get("page", 1)
            per_page = args.get("per_page", 20)
            return ChatService.get_user_chat_rooms(current_user.id, page, per_page)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    # @dual_role_required
    @bp.arguments(CreateChatRoomSchema)
    @bp.response(201, ChatRoomSchema)
    def post(self, room_data):
        """Create or get existing chat room"""
        try:
            # Determine user roles
            if current_user.current_role == "buyer":
                buyer_id = current_user.id
                seller_id = room_data["seller_id"]
            else:
                buyer_id = room_data["buyer_id"]
                seller_id = current_user.id

            room = ChatService.create_or_get_chat_room(
                buyer_id=buyer_id,
                seller_id=seller_id,
                product_id=room_data.get("product_id"),
                request_id=room_data.get("request_id"),
            )

            return {
                "id": room.id,
                "buyer_id": room.buyer_id,
                "seller_id": room.seller_id,
                "product_id": room.product_id,
                "request_id": room.request_id,
                "last_message_at": room.last_message_at.isoformat()
                if room.last_message_at
                else None,
                "unread_count_buyer": room.unread_count_buyer,
                "unread_count_seller": room.unread_count_seller,
            }
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/rooms/<int:room_id>/messages")
class ChatMessages(MethodView):
    @login_required
    # @dual_role_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, ChatMessageListSchema)
    def get(self, args, room_id):
        """Get messages for a chat room"""
        try:
            page = args.get("page", 1)
            per_page = args.get("per_page", 50)
            return ChatService.get_room_messages(
                room_id, current_user.id, page, per_page
            )
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    # @dual_role_required
    @bp.arguments(SendMessageSchema)
    @bp.response(201, ChatMessageSchema)
    def post(self, message_data, room_id):
        """Send a message in a chat room"""
        try:
            message = ChatService.send_message(
                room_id=room_id,
                sender_id=current_user.id,
                content=message_data["content"],
                message_type=message_data.get("message_type", "text"),
                message_data=message_data.get("message_data"),
            )

            return {
                "id": message.id,
                "room_id": message.room_id,
                "sender_id": message.sender_id,
                "content": message.content,
                "message_type": message.message_type,
                "message_data": message.message_data,
                "is_read": message.is_read,
                "created_at": message.created_at.isoformat(),
            }
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/rooms/<int:room_id>/read")
class MarkAsRead(MethodView):
    @login_required
    # @dual_role_required
    @bp.response(200)
    def post(self, room_id):
        """Mark messages as read in a chat room"""
        try:
            ChatService.mark_messages_as_read(room_id, current_user.id)
            return {"message": "Messages marked as read"}
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/rooms/<int:room_id>/offers")
class ChatOffers(MethodView):
    @login_required
    # @dual_role_required
    @bp.arguments(SendMessageSchema)
    @bp.response(201, ChatMessageSchema)
    def post(self, offer_data, room_id):
        """Send an offer in a chat room"""
        try:
            message = ChatService.send_offer(
                room_id=room_id,
                sender_id=current_user.id,
                product_id=offer_data["product_id"],
                price=offer_data["price"],
                message=offer_data.get("message", ""),
            )

            return {
                "id": message.id,
                "room_id": message.room_id,
                "sender_id": message.sender_id,
                "content": message.content,
                "message_type": message.message_type,
                "message_data": message.message_data,
                "is_read": message.is_read,
                "created_at": message.created_at.isoformat(),
            }
        except APIError as e:
            abort(e.status_code, message=e.message)
