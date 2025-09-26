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
    ChatMessageReactionCreateSchema,
    ChatMessageReactionSummarySchema,
)
from .services import ChatService, ChatReactionService, DiscountService

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


# Reaction Routes for Chat Messages
# -----------------------------------------------
@bp.route("/messages/<int:message_id>/reactions")
class ChatMessageReactions(MethodView):
    @bp.response(200, ChatMessageReactionSummarySchema(many=True))
    def get(self, message_id):
        """Get all reactions for a chat message"""
        try:
            user_id = current_user.id if current_user.is_authenticated else None
            return ChatReactionService.get_message_reactions(message_id, user_id)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @bp.arguments(ChatMessageReactionCreateSchema)
    @bp.response(201)
    def post(self, reaction_data, message_id):
        """Add a reaction to a chat message"""
        try:
            return ChatReactionService.add_message_reaction(
                current_user.id, message_id, reaction_data["reaction_type"]
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/messages/<int:message_id>/reactions/<reaction_type>")
class ChatMessageReactionDetail(MethodView):
    @login_required
    @bp.response(204)
    def delete(self, message_id, reaction_type):
        """Remove a reaction from a chat message"""
        try:
            ChatReactionService.remove_message_reaction(
                current_user.id, message_id, reaction_type
            )
            return "", 204
        except APIError as e:
            abort(e.status_code, message=e.message)


# Discount Routes for Chat
# -----------------------------------------------
@bp.route("/rooms/<int:room_id>/discounts")
class ChatRoomDiscounts(MethodView):
    @login_required
    @bp.response(200)
    def get(self, room_id):
        """Get active discount offers for a chat room"""
        try:
            discounts = DiscountService.get_active_discounts_for_user(
                current_user.id, room_id
            )
            return {"discounts": discounts}
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @bp.arguments(
        {
            "discount_type": {
                "type": "string",
                "required": True,
                "enum": ["percentage", "fixed_amount"],
            },
            "discount_value": {"type": "number", "required": True, "minimum": 0.01},
            "minimum_order_amount": {"type": "number", "minimum": 0},
            "maximum_discount_amount": {"type": "number", "minimum": 0},
            "expires_at": {"type": "string", "required": True, "format": "date-time"},
            "usage_limit": {"type": "integer", "minimum": 1, "default": 1},
            "product_id": {"type": "string"},
            "discount_message": {"type": "string"},
            "discount_code": {"type": "string"},
            "metadata": {"type": "object"},
        }
    )
    @bp.response(201)
    def post(self, discount_data, room_id):
        """Create a new discount offer in a chat room (seller only)"""
        try:
            discount = DiscountService.create_discount_offer(
                seller_id=current_user.id, room_id=room_id, discount_data=discount_data
            )
            return discount, 201
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/discounts/<int:discount_id>/respond")
class DiscountResponse(MethodView):
    @login_required
    @bp.arguments(
        {
            "response": {
                "type": "string",
                "required": True,
                "enum": ["accepted", "rejected"],
            },
            "response_message": {"type": "string"},
        }
    )
    @bp.response(200)
    def post(self, response_data, discount_id):
        """Respond to a discount offer (buyer only)"""
        try:
            result = DiscountService.respond_to_discount(
                buyer_id=current_user.id,
                discount_id=discount_id,
                response=response_data["response"],
                response_message=response_data.get("response_message"),
            )
            return result
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/discounts/<int:discount_id>/apply")
class DiscountApplication(MethodView):
    @login_required
    @bp.arguments(
        {"order_amount": {"type": "number", "required": True, "minimum": 0.01}}
    )
    @bp.response(200)
    def post(self, application_data, discount_id):
        """Apply a discount to an order (validate and calculate discount amount)"""
        try:
            success, discount_amount, message = DiscountService.apply_discount_to_order(
                user_id=current_user.id,
                discount_id=discount_id,
                order_amount=application_data["order_amount"],
            )
            return {
                "success": success,
                "discount_amount": discount_amount,
                "message": message,
                "order_amount": application_data["order_amount"],
                "final_amount": application_data["order_amount"] - discount_amount,
            }
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/discounts/<int:discount_id>/cancel")
class DiscountCancellation(MethodView):
    @login_required
    @bp.response(200)
    def post(self, discount_id):
        """Cancel a discount offer (seller only)"""
        try:
            result = DiscountService.cancel_discount(
                seller_id=current_user.id, discount_id=discount_id
            )
            return result
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/discounts/my-active")
class MyActiveDiscounts(MethodView):
    @login_required
    @bp.response(200)
    def get(self):
        """Get all active discount offers for the current user"""
        try:
            discounts = DiscountService.get_active_discounts_for_user(current_user.id)
            return {"discounts": discounts}
        except APIError as e:
            abort(e.status_code, message=e.message)
