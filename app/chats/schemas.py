# package imports
from marshmallow import Schema, fields, validate

# project imports
from app.libs.schemas import PaginationSchema
from app.libs.constants import REACTION_EMOJIS


class ChatRoomSchema(Schema):
    """Schema for chat room data"""

    id = fields.Integer(required=True)
    buyer_id = fields.String(required=True)
    seller_id = fields.String(required=True)
    product_id = fields.String(allow_none=True)
    request_id = fields.String(allow_none=True)
    last_message_at = fields.DateTime(allow_none=True)
    unread_count_buyer = fields.Integer(default=0)
    unread_count_seller = fields.Integer(default=0)


class ChatMessageSchema(Schema):
    """Schema for chat message data"""

    id = fields.Integer(required=True)
    room_id = fields.Integer(required=True)
    sender_id = fields.String(required=True)
    sender = fields.Nested("UserBasicSchema", required=True)
    content = fields.String(required=True)
    message_type = fields.String(
        validate=validate.OneOf(["text", "image", "product", "offer"]), default="text"
    )
    message_data = fields.Dict(allow_none=True)
    is_read = fields.Boolean(default=False)
    read_at = fields.DateTime(allow_none=True)
    created_at = fields.DateTime(required=True)


class ChatRoomListSchema(PaginationSchema):
    """Schema for paginated chat room list"""

    rooms = fields.List(fields.Nested("ChatRoomListItemSchema"), required=True)


class ChatMessageListSchema(PaginationSchema):
    """Schema for paginated chat message list"""

    messages = fields.List(fields.Nested(ChatMessageSchema), required=True)


class CreateChatRoomSchema(Schema):
    """Schema for creating a chat room"""

    buyer_id = fields.String(required=False)  # Required if current user is seller
    seller_id = fields.String(required=False)  # Required if current user is buyer
    product_id = fields.String(allow_none=True)
    request_id = fields.String(allow_none=True)


class SendMessageSchema(Schema):
    """Schema for sending a message"""

    content = fields.String(required=True, validate=validate.Length(min=1, max=1000))
    message_type = fields.String(
        validate=validate.OneOf(["text", "image", "product", "offer"]), default="text"
    )
    message_data = fields.Dict(allow_none=True)


class SendOfferSchema(Schema):
    """Schema for sending an offer"""

    product_id = fields.String(required=True)
    price = fields.Float(required=True, validate=validate.Range(min=0))
    message = fields.String(allow_none=True, validate=validate.Length(max=500))


class OfferResponseSchema(Schema):
    """Schema for responding to an offer"""

    response = fields.String(
        required=True, validate=validate.OneOf(["accept", "reject", "counter"])
    )
    message = fields.String(allow_none=True, validate=validate.Length(max=500))
    counter_price = fields.Float(allow_none=True, validate=validate.Range(min=0))


class TypingStatusSchema(Schema):
    """Schema for typing status"""

    is_typing = fields.Boolean(required=True)


class OnlineStatusSchema(Schema):
    """Schema for online status"""

    is_online = fields.Boolean(required=True)


class ChatRoomDetailSchema(Schema):
    """Schema for detailed chat room information"""

    id = fields.Integer(required=True)
    buyer = fields.Nested("UserBasicSchema", required=True)
    seller = fields.Nested("UserBasicSchema", required=True)
    product = fields.Nested("ProductBasicSchema", allow_none=True)
    request = fields.Nested("RequestBasicSchema", allow_none=True)
    last_message = fields.Nested(ChatMessageSchema, allow_none=True)
    unread_count = fields.Integer(required=True)
    last_message_at = fields.DateTime(allow_none=True)


class UserBasicSchema(Schema):
    """Basic user information for chat"""

    id = fields.String(required=True)
    username = fields.String(required=True)
    profile_picture = fields.String(allow_none=True)
    is_seller = fields.Boolean(required=True)


class LastMessagePreviewSchema(Schema):
    """Schema for last message preview in chat room list"""

    id = fields.Integer(required=True)
    sender_id = fields.String(required=True)
    content = fields.String(required=True)
    message_type = fields.String(required=True)
    created_at = fields.DateTime(required=True)


class ChatRoomListItemSchema(Schema):
    """Schema for enriched chat room list item"""

    id = fields.Integer(required=True)
    other_user = fields.Nested("UserBasicSchema", required=True)
    product = fields.Nested("ProductBasicSchema", allow_none=True)
    request = fields.Nested("RequestBasicSchema", allow_none=True)
    last_message = fields.Nested(LastMessagePreviewSchema, allow_none=True)
    unread_count = fields.Integer(required=True)
    last_message_at = fields.DateTime(allow_none=True)


class ProductBasicSchema(Schema):
    """Basic product information for chat"""

    id = fields.String(required=True)
    name = fields.String(required=True)
    price = fields.Float(required=True)
    image = fields.String(allow_none=True)


class RequestBasicSchema(Schema):
    """Basic request information for chat"""

    id = fields.String(required=True)
    title = fields.String(required=True)
    description = fields.String(allow_none=True)


# Reaction Schemas for Chat Messages
class ChatMessageReactionSchema(Schema):
    """Schema for chat message reactions"""

    id = fields.Int(dump_only=True)
    message_id = fields.Int(dump_only=True)
    user_id = fields.Str(dump_only=True)
    reaction_type = fields.Str(dump_only=True)
    emoji = fields.Str(dump_only=True)
    created_at = fields.DateTime(dump_only=True)

    def get_emoji(self, obj):
        """Get emoji for reaction type"""
        return REACTION_EMOJIS.get(obj.reaction_type.value, "👍")


class ChatMessageReactionCreateSchema(Schema):
    """Schema for creating chat message reactions"""

    reaction_type = fields.Str(
        required=True, validate=validate.OneOf(list(REACTION_EMOJIS.keys()))
    )


class ChatMessageReactionSummarySchema(Schema):
    """Schema for chat message reaction summaries"""

    reaction_type = fields.Str(dump_only=True)
    emoji = fields.Str(dump_only=True)
    count = fields.Int(dump_only=True)
    has_reacted = fields.Bool(dump_only=True)

    def get_emoji(self, obj):
        """Get emoji for reaction type"""
        return REACTION_EMOJIS.get(obj.reaction_type, "👍")
