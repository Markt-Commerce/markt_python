from marshmallow import Schema, fields, validate, ValidationError
from enum import Enum
from app.libs.schemas import PaginationSchema
from .models import MediaType, MediaVariantType


class MediaTypeEnum(Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"


class MediaVariantTypeEnum(Enum):
    ORIGINAL = "original"
    THUMBNAIL = "thumbnail"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    MOBILE = "mobile"
    TABLET = "tablet"
    DESKTOP = "desktop"
    SOCIAL_SQUARE = "social_square"
    SOCIAL_STORY = "social_story"
    SOCIAL_POST = "social_post"


class MediaVariantSchema(Schema):
    """Schema for media variants"""

    id = fields.Int(dump_only=True)
    variant_type = fields.Enum(MediaVariantTypeEnum, by_value=True)
    storage_key = fields.Str(dump_only=True)
    width = fields.Int()
    height = fields.Int()
    file_size = fields.Int()
    quality = fields.Int()
    format = fields.Str()
    processing_time = fields.Float()
    url = fields.Method("get_variant_url", dump_only=True)

    def get_variant_url(self, obj):
        return obj.get_url() if hasattr(obj, "get_url") else None


class MediaSchema(Schema):
    """Schema for media objects"""

    id = fields.Int(dump_only=True)
    storage_key = fields.Str(dump_only=True)
    media_type = fields.Enum(MediaTypeEnum, by_value=True)
    mime_type = fields.Str()
    width = fields.Int()
    height = fields.Int()
    file_size = fields.Int()
    duration = fields.Int(allow_none=True)
    alt_text = fields.Str(validate=validate.Length(max=255))
    caption = fields.Str()
    is_public = fields.Bool(default=True)
    user_id = fields.Str()

    # Additional metadata
    original_filename = fields.Str()
    processing_status = fields.Str()
    background_removed = fields.Bool()
    compression_quality = fields.Int()
    exif_data = fields.Dict()

    # URLs
    original_url = fields.Method("get_original_url", dump_only=True)
    thumbnail_url = fields.Method("get_thumbnail_url", dump_only=True)
    variants = fields.Nested(MediaVariantSchema, many=True, dump_only=True)

    # Responsive URLs
    mobile_url = fields.Method("get_mobile_url", dump_only=True)
    tablet_url = fields.Method("get_tablet_url", dump_only=True)
    desktop_url = fields.Method("get_desktop_url", dump_only=True)

    # Social media URLs
    social_square_url = fields.Method("get_social_square_url", dump_only=True)
    social_story_url = fields.Method("get_social_story_url", dump_only=True)
    social_post_url = fields.Method("get_social_post_url", dump_only=True)

    # Timestamps
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def get_original_url(self, obj):
        return obj.get_url() if hasattr(obj, "get_url") else None

    def get_thumbnail_url(self, obj):
        return (
            obj.get_url(MediaVariantType.THUMBNAIL) if hasattr(obj, "get_url") else None
        )

    def get_mobile_url(self, obj):
        return obj.get_url(MediaVariantType.MOBILE) if hasattr(obj, "get_url") else None

    def get_tablet_url(self, obj):
        return obj.get_url(MediaVariantType.TABLET) if hasattr(obj, "get_url") else None

    def get_desktop_url(self, obj):
        return (
            obj.get_url(MediaVariantType.DESKTOP) if hasattr(obj, "get_url") else None
        )

    def get_social_square_url(self, obj):
        return (
            obj.get_url(MediaVariantType.SOCIAL_SQUARE)
            if hasattr(obj, "get_url")
            else None
        )

    def get_social_story_url(self, obj):
        return (
            obj.get_url(MediaVariantType.SOCIAL_STORY)
            if hasattr(obj, "get_url")
            else None
        )

    def get_social_post_url(self, obj):
        return (
            obj.get_url(MediaVariantType.SOCIAL_POST)
            if hasattr(obj, "get_url")
            else None
        )

    def filter_media_objects(self, media_list):
        """Filter out soft-deleted media from a list"""
        from .models import Media

        if not media_list:
            return []
        return Media.filter_active_media(media_list)


class MediaUploadSchema(Schema):
    """Schema for media upload requests"""

    alt_text = fields.Str(validate=validate.Length(max=255), required=False)
    caption = fields.Str(required=False)
    is_public = fields.Bool(default=True)

    # Optional processing options
    remove_background = fields.Bool(default=False)  # Placeholder for future
    compression_quality = fields.Int(
        validate=validate.Range(min=1, max=100), default=85
    )

    # Social media optimization
    optimize_for_social = fields.Bool(default=True)
    platforms = fields.List(fields.Str(), default=["instagram", "facebook", "twitter"])


class MediaUploadResponseSchema(Schema):
    """Schema for media upload responses"""

    success = fields.Bool()
    media = fields.Nested(MediaSchema)
    variants = fields.Nested(MediaVariantSchema, many=True)
    urls = fields.Dict()
    processing_time = fields.Float()
    message = fields.Str()


class MediaListSchema(Schema):
    """Schema for media list responses"""

    media = fields.Nested(MediaSchema, many=True)
    total = fields.Int()
    page = fields.Int()
    per_page = fields.Int()
    has_next = fields.Bool()
    has_prev = fields.Bool()


class MediaFilterSchema(Schema):
    """Schema for media filtering"""

    media_type = fields.Enum(MediaTypeEnum, by_value=True, required=False)
    user_id = fields.Str(required=False)
    is_public = fields.Bool(required=False)
    processing_status = fields.Str(required=False)
    created_after = fields.DateTime(required=False)
    created_before = fields.DateTime(required=False)
    page = fields.Int(validate=validate.Range(min=1), default=1)
    per_page = fields.Int(validate=validate.Range(min=1, max=100), default=20)


class SocialMediaOptimizationSchema(Schema):
    """Schema for social media optimization requests"""

    platform = fields.Str(
        validate=validate.OneOf(["instagram", "facebook", "twitter", "linkedin"]),
        required=True,
    )
    post_type = fields.Str(
        validate=validate.OneOf(["story", "post", "reel", "carousel"]), required=True
    )
    aspect_ratio = fields.Str(required=False)  # 1:1, 16:9, 9:16, etc.


class SocialMediaOptimizationResponseSchema(Schema):
    """Schema for social media optimization responses"""

    platform = fields.Str()
    post_type = fields.Str()
    optimized_url = fields.Str()
    original_url = fields.Str()
    dimensions = fields.Dict()
    file_size = fields.Int()


class ProductImageSchema(Schema):
    """Schema for product images"""

    id = fields.Int(dump_only=True)
    product_id = fields.Str(required=True)
    media_id = fields.Int(required=True)
    sort_order = fields.Int(default=0)
    is_featured = fields.Bool(default=False)
    alt_text = fields.Str(validate=validate.Length(max=255))
    media = fields.Nested(MediaSchema, dump_only=True)

    def get_filtered_media(self, obj):
        """Get media object, filtering out soft-deleted media"""
        if hasattr(obj, "media") and obj.media:
            from .models import Media

            if not obj.media.is_deleted:
                return obj.media
        return None


class SocialMediaPostSchema(Schema):
    """Schema for social media posts"""

    id = fields.Int(dump_only=True)
    post_id = fields.Str(required=True)
    media_id = fields.Int(required=True)
    platform = fields.Str(
        validate=validate.OneOf(["instagram", "facebook", "twitter", "linkedin"])
    )
    post_type = fields.Str(
        validate=validate.OneOf(["story", "post", "reel", "carousel"])
    )
    sort_order = fields.Int(default=0)
    aspect_ratio = fields.Str()
    optimized_for_platform = fields.Bool(default=True)
    media = fields.Nested(MediaSchema, dump_only=True)

    def get_filtered_media(self, obj):
        """Get media object, filtering out soft-deleted media"""
        if hasattr(obj, "media") and obj.media:
            from .models import Media

            if not obj.media.is_deleted:
                return obj.media
        return None


class RequestImageSchema(Schema):
    """Schema for buyer request images"""

    id = fields.Int(dump_only=True)
    request_id = fields.Str(required=True)
    media_id = fields.Int(required=True)
    is_primary = fields.Bool(default=False)
    media = fields.Nested(MediaSchema, dump_only=True)

    def get_filtered_media(self, obj):
        """Get media object, filtering out soft-deleted media"""
        if hasattr(obj, "media") and obj.media:
            from .models import Media

            if not obj.media.is_deleted:
                return obj.media
        return None


class MediaDeleteSchema(Schema):
    """Schema for media deletion responses"""

    success = fields.Bool()
    message = fields.Str()
    deleted_files = fields.Int()


class MediaStatsSchema(Schema):
    """Schema for media statistics"""

    total_media = fields.Int()
    total_images = fields.Int()
    total_videos = fields.Int()
    total_size = fields.Int()  # in bytes
    average_file_size = fields.Float()
    variants_generated = fields.Int()
    processing_time_avg = fields.Float()


# Validation functions
def validate_file_size(file_size: int, max_size: int) -> bool:
    """Validate file size"""
    if file_size > max_size:
        raise ValidationError(
            f"File size exceeds maximum allowed size of {max_size} bytes"
        )
    return True


def validate_image_dimensions(
    width: int, height: int, max_width: int, max_height: int
) -> bool:
    """Validate image dimensions"""
    if width > max_width or height > max_height:
        raise ValidationError(
            f"Image dimensions exceed maximum allowed size of {max_width}x{max_height}"
        )
    return True


def validate_video_duration(duration: int, max_duration: int) -> bool:
    """Validate video duration"""
    if duration > max_duration:
        raise ValidationError(
            f"Video duration exceeds maximum allowed duration of {max_duration} seconds"
        )
    return True
