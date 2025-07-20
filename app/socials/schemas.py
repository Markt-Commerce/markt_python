from marshmallow import Schema, fields, validate

from app.libs.schemas import PaginationSchema
from app.libs.errors import ValidationError

from app.products.schemas import ProductSchema
from app.users.schemas import UserSimpleSchema

from .models import (
    FollowType,
    PostStatus,
    NicheStatus,
    NicheVisibility,
    NicheMembershipRole,
)


# Niche/Community Schemas
class NicheSchema(Schema):
    """Schema for niche communities"""

    id = fields.Str(dump_only=True)
    name = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    description = fields.Str(required=True, validate=validate.Length(min=10, max=2000))
    slug = fields.Str(dump_only=True)
    status = fields.Enum(NicheStatus, by_value=True, dump_only=True)
    visibility = fields.Enum(NicheVisibility, by_value=True, dump_only=True)

    # Community settings
    allow_buyer_posts = fields.Bool(dump_only=True)
    allow_seller_posts = fields.Bool(dump_only=True)
    require_approval = fields.Bool(dump_only=True)
    max_members = fields.Int(dump_only=True)

    # Metadata
    categories = fields.List(fields.Nested("CategorySchema"), dump_only=True)
    tags = fields.List(fields.Str(), dump_only=True)
    rules = fields.List(fields.Str(), dump_only=True)
    settings = fields.Dict(dump_only=True)

    # Statistics
    member_count = fields.Int(dump_only=True)
    post_count = fields.Int(dump_only=True)

    # Timestamps
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    # Relationships
    category = fields.Nested("CategorySchema", dump_only=True)


class NicheSearchResultSchema(Schema):
    items = fields.List(fields.Nested(NicheSchema))
    pagination = fields.Nested(PaginationSchema)


class NicheCreateSchema(Schema):
    """Schema for creating niche communities"""

    name = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    description = fields.Str(required=True, validate=validate.Length(min=10, max=2000))
    visibility = fields.Enum(
        NicheVisibility, by_value=True, missing=NicheVisibility.PUBLIC
    )
    allow_buyer_posts = fields.Bool(missing=True)
    allow_seller_posts = fields.Bool(missing=True)
    require_approval = fields.Bool(missing=False)
    max_members = fields.Int(validate=validate.Range(min=1, max=100000), missing=10000)
    category_ids = fields.List(fields.Int(), missing=[])
    tags = fields.List(fields.Str(), missing=[])
    rules = fields.List(fields.Str(), missing=[])
    settings = fields.Dict(missing={})


class NicheUpdateSchema(Schema):
    """Schema for updating niche communities"""

    name = fields.Str(validate=validate.Length(min=1, max=100))
    description = fields.Str(validate=validate.Length(min=10, max=2000))
    visibility = fields.Enum(NicheVisibility, by_value=True)
    allow_buyer_posts = fields.Bool()
    allow_seller_posts = fields.Bool()
    require_approval = fields.Bool()
    max_members = fields.Int(validate=validate.Range(min=1, max=100000))
    category_ids = fields.List(fields.Int())
    tags = fields.List(fields.Str())
    rules = fields.List(fields.Str())
    settings = fields.Dict()


class NichePostSchema(Schema):
    """Schema for posts within niches"""

    id = fields.Int(dump_only=True)
    niche_id = fields.Str(dump_only=True)
    post_id = fields.Str(dump_only=True)
    status = fields.Enum(PostStatus, by_value=True, dump_only=True)
    is_pinned = fields.Bool(dump_only=True)
    is_featured = fields.Bool(dump_only=True)
    is_approved = fields.Bool(dump_only=True)
    moderated_by = fields.Str(dump_only=True, allow_none=True)
    moderated_at = fields.DateTime(dump_only=True, allow_none=True)
    niche_likes = fields.Int(dump_only=True)
    niche_comments = fields.Int(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    # Nested post data
    post = fields.Nested("PostDetailSchema", dump_only=True)
    niche = fields.Nested("NicheSchema", dump_only=True)


class NichePostCreateSchema(Schema):
    """Schema for creating posts in niches"""

    caption = fields.Str(required=False)
    social_media = fields.List(fields.Nested("SocialMediaPostSchema"), required=False)
    products = fields.List(fields.Nested("PostProductSchema"), required=False)
    status = fields.Str(
        required=False, validate=validate.OneOf(["draft", "active"]), default="draft"
    )


class NichePostResponseSchema(Schema):
    """Schema for niche post creation response"""

    post = fields.Nested("PostDetailSchema", dump_only=True)
    niche_post = fields.Nested("NichePostSchema", dump_only=True)
    requires_approval = fields.Bool(dump_only=True)
    is_approved = fields.Bool(dump_only=True)


class NichePostListSchema(Schema):
    """Schema for listing niche posts"""

    items = fields.List(fields.Nested("NichePostSchema"), dump_only=True)
    pagination = fields.Nested("PaginationSchema", dump_only=True)


class NichePostApprovalSchema(Schema):
    """Schema for approving/rejecting niche posts"""

    action = fields.Str(required=True, validate=validate.OneOf(["approve", "reject"]))
    reason = fields.Str(required=False)  # Required for rejections


class NicheSearchSchema(Schema):
    """Schema for searching niche communities"""

    search = fields.Str(allow_none=True)
    category_ids = fields.List(fields.Int(), allow_none=True)
    visibility = fields.Enum(NicheVisibility, by_value=True, allow_none=True)
    page = fields.Int(validate=validate.Range(min=1), missing=1)
    per_page = fields.Int(validate=validate.Range(min=1, max=100), missing=20)


class NicheMembershipSchema(Schema):
    """Schema for niche memberships"""

    id = fields.Int(dump_only=True)
    niche_id = fields.Str(dump_only=True)
    user_id = fields.Str(dump_only=True)
    role = fields.Enum(NicheMembershipRole, by_value=True, dump_only=True)

    # Membership details
    joined_at = fields.DateTime(dump_only=True)
    invited_by = fields.Str(dump_only=True)
    is_active = fields.Bool(dump_only=True)

    # Moderation flags
    is_banned = fields.Bool(dump_only=True)
    banned_until = fields.DateTime(dump_only=True)
    ban_reason = fields.Str(dump_only=True)

    # Activity tracking
    last_activity = fields.DateTime(dump_only=True)
    post_count = fields.Int(dump_only=True)
    comment_count = fields.Int(dump_only=True)

    # Relationships
    user = fields.Nested("UserSimpleSchema", dump_only=True)
    inviter = fields.Nested("UserSimpleSchema", dump_only=True)
    niche = fields.Nested(NicheSchema, dump_only=True)


class NicheMembershipSearchResultSchema(Schema):
    items = fields.List(fields.Nested(NicheMembershipSchema))
    pagination = fields.Nested(PaginationSchema)


class NicheModerationActionSchema(Schema):
    """Schema for niche moderation actions"""

    id = fields.Int(dump_only=True)
    niche_id = fields.Str(dump_only=True)
    moderator_id = fields.Str(dump_only=True)
    target_user_id = fields.Str(dump_only=True)

    # Action details
    action_type = fields.Str(dump_only=True)
    reason = fields.Str(dump_only=True)
    duration = fields.TimeDelta(dump_only=True)

    # Target details
    target_type = fields.Str(dump_only=True)
    target_id = fields.Str(dump_only=True)

    # Action metadata
    is_active = fields.Bool(dump_only=True)
    expires_at = fields.DateTime(dump_only=True)

    created_at = fields.DateTime(dump_only=True)

    # Relationships
    moderator = fields.Nested("UserSimpleSchema", dump_only=True)
    target_user = fields.Nested("UserSimpleSchema", dump_only=True)


class ModerationActionSchema(Schema):
    """Schema for creating moderation actions"""

    target_user_id = fields.Str(required=True)
    action_type = fields.Str(
        required=True, validate=validate.OneOf(["ban", "warn", "remove_post"])
    )
    reason = fields.Str(required=True, validate=validate.Length(min=1, max=500))
    duration = fields.TimeDelta(allow_none=True)
    target_type = fields.Str(
        validate=validate.OneOf(["user", "post", "comment"]), missing="user"
    )
    target_id = fields.Str(allow_none=True)
    banned_until = fields.DateTime(allow_none=True)


class ShareSchema(Schema):
    """Schema for sharing content"""

    id = fields.Str(dump_only=True)
    user_id = fields.Str(required=True)
    content_type = fields.Str(
        required=True, validate=validate.OneOf(["post", "product"])
    )
    content_id = fields.Str(required=True)
    platform = fields.Str(validate=validate.OneOf(["facebook", "twitter", "instagram"]))
    created_at = fields.DateTime(dump_only=True)


class CommentSchema(Schema):
    """Schema for comments"""

    id = fields.Int(dump_only=True)
    user_id = fields.Str(dump_only=True)
    content = fields.Str(required=True, validate=validate.Length(min=1, max=1000))
    parent_id = fields.Int(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
    user = fields.Nested("UserSimpleSchema", dump_only=True)


class StorySchema(Schema):
    """Schema for ephemeral stories"""

    id = fields.Str(dump_only=True)
    user_id = fields.Str(required=True)
    media_url = fields.Str(required=True)
    media_type = fields.Str(validate=validate.OneOf(["image", "video"]))
    duration = fields.Int(validate=validate.Range(min=1, max=24))
    created_at = fields.DateTime(dump_only=True)
    expires_at = fields.DateTime(dump_only=True)
    user = fields.Nested("UserSimpleSchema", dump_only=True)


class CollectionSchema(Schema):
    """Schema for product collections"""

    id = fields.Str(dump_only=True)
    name = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    description = fields.Str(validate=validate.Length(max=500))
    is_public = fields.Bool(missing=True)
    is_collaborative = fields.Bool(missing=False)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
    user = fields.Nested("UserSimpleSchema", dump_only=True)


# Note: Media upload schemas are now in app.media.schemas
# Use SocialMediaPostSchema from app.media.schemas for media operations


class PostProductSchema(Schema):
    product_id = fields.Str(required=True)


class PostCreateSchema(Schema):
    caption = fields.Str(required=False)
    category_ids = fields.List(fields.Int(), required=False)
    tags = fields.List(fields.Str(), required=False)
    media_ids = fields.List(
        fields.Int(), description="List of media IDs to link to post"
    )
    # Note: Media files can also be uploaded separately via media endpoints
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
    niche_context = fields.Dict(dump_only=True)
    categories = fields.List(fields.Nested("CategorySchema"), dump_only=True)


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
    social_media = fields.List(fields.Nested("SocialMediaPostSchema"), required=False)
    products = fields.List(fields.Nested(PostProductSchema), required=False)


class CommentCreateSchema(Schema):
    content = fields.Str(required=True)
    parent_id = fields.Int(required=False)


class CommentUpdateSchema(Schema):
    content = fields.Str(required=True)


class PostDetailSchema(PostSchema):
    social_media = fields.List(fields.Nested("SocialMediaPostSchema"))
    products = fields.List(fields.Nested(PostProductSchema))
    user = fields.Nested("UserSimpleSchema")
    status = fields.Enum(PostStatus, by_value=True, dump_only=True)


class PostDetailSearchResultSchema(Schema):
    items = fields.List(fields.Nested(PostDetailSchema))
    pagination = fields.Nested(PaginationSchema)


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


class NicheFeedInfoSchema(Schema):
    """Schema for niche information in feed responses"""

    id = fields.Str(dump_only=True)
    name = fields.Str(dump_only=True)
    slug = fields.Str(dump_only=True)
    visibility = fields.Str(dump_only=True)
    is_pinned = fields.Bool(dump_only=True)
    is_featured = fields.Bool(dump_only=True)
    niche_likes = fields.Int(dump_only=True)
    niche_comments = fields.Int(dump_only=True)


class FeedPostSchema(Schema):
    """Schema for posts in feed responses with enhanced niche information"""

    id = fields.Str(dump_only=True)
    type = fields.Str(dump_only=True)
    caption = fields.Str(dump_only=True)
    seller = fields.Dict(dump_only=True)
    media = fields.List(fields.Dict(), dump_only=True)
    likes_count = fields.Int(dump_only=True)
    comments_count = fields.Int(dump_only=True)
    created_at = fields.Str(dump_only=True)
    score = fields.Float(dump_only=True)
    niche = fields.Nested(NicheFeedInfoSchema, dump_only=True, allow_none=True)


class FeedProductSchema(Schema):
    """Schema for products in feed responses"""

    id = fields.Str(dump_only=True)
    type = fields.Str(dump_only=True)
    name = fields.Str(dump_only=True)
    description = fields.Str(dump_only=True)
    price = fields.Float(dump_only=True)
    seller = fields.Dict(dump_only=True)
    images = fields.List(fields.Dict(), dump_only=True)
    rating = fields.Float(dump_only=True)
    reviews_count = fields.Int(dump_only=True)
    created_at = fields.Str(dump_only=True)
    score = fields.Float(dump_only=True)


class FeedResponseSchema(Schema):
    """Schema for feed responses with mixed content types"""

    items = fields.List(fields.Dict(), dump_only=True)  # Mixed post/product items
    pagination = fields.Nested(PaginationSchema, dump_only=True)
