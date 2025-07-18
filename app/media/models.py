from enum import Enum
from external.database import db
from app.libs.models import BaseModel
from main.config import settings


class MediaType(Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"


class MediaVariantType(Enum):
    ORIGINAL = "original"
    THUMBNAIL = "thumbnail"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    # Responsive variants for different screen sizes
    MOBILE = "mobile"
    TABLET = "tablet"
    DESKTOP = "desktop"
    # Social media optimized variants
    SOCIAL_SQUARE = "social_square"
    SOCIAL_STORY = "social_story"
    SOCIAL_POST = "social_post"


class Media(BaseModel):
    __tablename__ = "media"

    id = db.Column(db.Integer, primary_key=True)
    storage_key = db.Column(db.String(255), unique=True)  # S3/key path
    media_type = db.Column(db.Enum(MediaType))
    mime_type = db.Column(db.String(100))
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    file_size = db.Column(db.Integer)  # bytes
    duration = db.Column(db.Integer)  # for videos/audio in seconds
    alt_text = db.Column(db.String(255))
    caption = db.Column(db.Text)
    is_public = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"))

    # Additional metadata
    original_filename = db.Column(db.String(255))
    processing_status = db.Column(
        db.String(50), default="completed"
    )  # pending, processing, completed, failed
    background_removed = db.Column(
        db.Boolean, default=False
    )  # Placeholder for future background removal
    compression_quality = db.Column(db.Integer, default=85)  # JPEG quality used
    exif_data = db.Column(db.JSON)  # Store EXIF metadata

    # Relationships
    variants = db.relationship(
        "MediaVariant", back_populates="media", cascade="all, delete-orphan"
    )
    user = db.relationship("User", back_populates="media_uploads")

    def get_url(self, variant_type=MediaVariantType.ORIGINAL):
        """Get URL for specific variant or original"""
        if variant_type == MediaVariantType.ORIGINAL:
            return (
                f"https://{settings.AWS_S3_BUCKET}.s3.amazonaws.com/{self.storage_key}"
            )

        # Find specific variant
        variant = next(
            (v for v in self.variants if v.variant_type == variant_type), None
        )
        if variant:
            return f"https://{settings.AWS_S3_BUCKET}.s3.amazonaws.com/{variant.storage_key}"

        # Fallback to original
        return f"https://{settings.AWS_S3_BUCKET}.s3.amazonaws.com/{self.storage_key}"

    def get_best_variant_for_screen(self, screen_type="desktop"):
        """Get the best variant for a specific screen type"""
        variant_mapping = {
            "mobile": MediaVariantType.MOBILE,
            "tablet": MediaVariantType.TABLET,
            "desktop": MediaVariantType.DESKTOP,
        }

        target_variant = variant_mapping.get(screen_type, MediaVariantType.MEDIUM)
        return self.get_url(target_variant)


class MediaVariant(BaseModel):
    __tablename__ = "media_variants"

    id = db.Column(db.Integer, primary_key=True)
    media_id = db.Column(db.Integer, db.ForeignKey("media.id"))
    variant_type = db.Column(db.Enum(MediaVariantType))
    storage_key = db.Column(db.String(255))
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    file_size = db.Column(db.Integer)

    # Additional metadata for variants
    quality = db.Column(db.Integer, default=85)  # JPEG quality
    format = db.Column(db.String(10), default="JPEG")  # Image format
    processing_time = db.Column(db.Float)  # Processing time in seconds

    media = db.relationship("Media", back_populates="variants")

    def get_url(self):
        """Get URL for this variant"""
        return f"https://{settings.AWS_S3_BUCKET}.s3.amazonaws.com/{self.storage_key}"


class ProductImage(BaseModel):
    __tablename__ = "product_images"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"))
    media_id = db.Column(db.Integer, db.ForeignKey("media.id"))
    sort_order = db.Column(db.Integer, default=0)
    is_featured = db.Column(db.Boolean, default=False)
    alt_text = db.Column(db.String(255))

    product = db.relationship("Product", back_populates="images")
    media = db.relationship("Media")


class SocialMediaPost(BaseModel):
    __tablename__ = "social_media_posts"

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.String(12), db.ForeignKey("posts.id"))
    media_id = db.Column(db.Integer, db.ForeignKey("media.id"))
    platform = db.Column(db.String(50))  # instagram, facebook, twitter, etc.
    post_type = db.Column(db.String(50))  # story, post, reel, etc.
    sort_order = db.Column(db.Integer, default=0)

    # Social media specific metadata
    aspect_ratio = db.Column(db.String(20))  # 1:1, 16:9, 9:16, etc.
    optimized_for_platform = db.Column(db.Boolean, default=True)

    # Relationships
    post = db.relationship("Post", back_populates="social_media")
    media = db.relationship("Media")


class RequestImage(BaseModel):
    __tablename__ = "request_images"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(12), db.ForeignKey("buyer_requests.id"))
    media_id = db.Column(db.Integer, db.ForeignKey("media.id"))
    is_primary = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)

    request = db.relationship("BuyerRequest", back_populates="images")
    media = db.relationship("Media")
