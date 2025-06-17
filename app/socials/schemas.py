from marshmallow import Schema, fields, validate

from app.libs.schemas import PaginationSchema
from app.libs.errors import ValidationError

from app.products.schemas import ProductSchema
from app.users.schemas import UserSimpleSchema

from .models import FollowType, PostStatus


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
    status = fields.Str(
        required=False, validate=validate.OneOf(["draft", "active"]), default="draft"
    )


class PostSchema(Schema):
    id = fields.Str(dump_only=True)
    seller_id = fields.Int(dump_only=True)
    caption = fields.Str()
    created_at = fields.DateTime(dump_only=True)
    like_count = fields.Int(dump_only=True)
    comment_count = fields.Int(dump_only=True)


class SellerPostsSchema(Schema):
    items = fields.List(fields.Nested(PostSchema))
    pagination = fields.Nested(PaginationSchema)


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
    user = fields.Nested("UserSimpleSchema")


class PostStatusUpdateSchema(Schema):
    action = fields.Str(
        required=True,
        validate=validate.OneOf(["publish", "archive", "unarchive", "delete"]),
    )


class PostUpdateSchema(Schema):
    caption = fields.Str(required=False)
    media = fields.List(fields.Nested(PostMediaSchema), required=False)
    products = fields.List(fields.Nested(PostProductSchema), required=False)


class CommentCreateSchema(Schema):
    content = fields.Str(required=True)
    parent_id = fields.Int(required=False)


class CommentUpdateSchema(Schema):
    content = fields.Str(required=True)


class PostDetailSchema(PostSchema):
    media = fields.List(fields.Nested(PostMediaSchema))
    products = fields.List(fields.Nested(PostProductSchema))
    user = fields.Nested("UserSimpleSchema")
    status = fields.Enum(PostStatus, by_value=True, dump_only=True)


class PostCommentsSchema(Schema):
    items = fields.List(fields.Nested(PostCommentSchema))
    pagination = fields.Nested(PaginationSchema)


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


class ProductReviewSchema(Schema):
    id = fields.Int(dump_only=True)
    user_id = fields.Str(dump_only=True)
    product_id = fields.Str(dump_only=True)
    order_id = fields.Str(required=False)
    rating = fields.Int(validate=validate.Range(min=1, max=5))
    title = fields.Str(validate=validate.Length(max=100))
    content = fields.Str(required=True)
    upvotes = fields.Int(dump_only=True)
    is_verified = fields.Bool(dump_only=True)
    created_at = fields.DateTime(dump_only=True)

    user = fields.Nested(lambda: UserSimpleSchema(), dump_only=True)


class ProductReviewsSchema(Schema):
    items = fields.List(fields.Nested(ProductReviewSchema))
    pagination = fields.Nested(PaginationSchema)


class ReviewUpvoteSchema(Schema):
    success = fields.Bool()
    new_count = fields.Int()
