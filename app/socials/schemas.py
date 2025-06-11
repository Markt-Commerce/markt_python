from marshmallow import Schema, fields, validate
from app.libs.schemas import PaginationSchema
from app.libs.errors import ValidationError

from app.products.schemas import ProductSchema
from .models import FollowType


class ShareSchema(Schema):
    pass


class CommentSchema(Schema):
    pass


class StorySchema(Schema):
    pass


class CollectionSchema(Schema):
    pass


class PostMediaSchema(Schema):
    media_url = fields.Str(required=True)
    media_type = fields.Str(validate=validate.OneOf(["image", "video"]))
    sort_order = fields.Int()


class PostProductSchema(Schema):
    product_id = fields.Str(required=True)


class PostCreateSchema(Schema):
    caption = fields.Str(required=False)
    media = fields.List(fields.Nested(PostMediaSchema), required=False)
    products = fields.List(fields.Nested(PostProductSchema), required=False)


class PostSchema(Schema):
    id = fields.Str(dump_only=True)
    seller_id = fields.Int(dump_only=True)
    caption = fields.Str()
    created_at = fields.DateTime(dump_only=True)
    like_count = fields.Method("get_like_count")
    comment_count = fields.Method("get_comment_count")

    def get_like_count(self, obj):
        return len(obj.likes)

    def get_comment_count(self, obj):
        return len(obj.comments)


class PostDetailSchema(PostSchema):
    media = fields.List(fields.Nested(PostMediaSchema))
    products = fields.List(fields.Nested(PostProductSchema))
    user = fields.Nested("UserProfileSchema")


class SellerPostsSchema(Schema):
    items = fields.List(fields.Nested(PostSchema))
    pagination = fields.Nested(PostDetailSchema)


class PostLikeSchema(Schema):
    user_id = fields.Str(dump_only=True)
    post_id = fields.Str(dump_only=True)
    created_at = fields.DateTime(dump_only=True)


class PostCommentSchema(Schema):
    id = fields.Int(dump_only=True)
    user_id = fields.Str(dump_only=True)
    post_id = fields.Str(dump_only=True)
    content = fields.Str(required=True)
    created_at = fields.DateTime(dump_only=True)
    user = fields.Nested("UserProfileSchema")


class FollowSchema(Schema):
    follower_id = fields.Str(dump_only=True)
    followee_id = fields.Str(dump_only=True)
    follow_type = fields.Enum(FollowType, by_value=True)
    created_at = fields.DateTime(dump_only=True)


class PostOrProductField(fields.Field):
    def _serialize(self, value, attr, obj, **kwargs):
        if obj["type"] == "post":
            return PostSchema().dump(value)
        elif obj["type"] == "product":
            return ProductSchema().dump(value)
        raise ValidationError("Unknown feed item type")
    

class FeedItemSchema(Schema):
    type = fields.Str(required=True)
    data = fields.Nested(PostSchema)
    score = fields.Float(dump_only=True)
    created_at = fields.DateTime(dump_only=True)


class HybridFeedSchema(Schema):
    items = fields.List(fields.Nested(FeedItemSchema))
    pagination = fields.Nested(PaginationSchema)
