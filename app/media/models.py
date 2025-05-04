from enum import Enum
from external.database import db
from app.libs.models import BaseModel


class MediaType(Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"


class MediaVariantType(Enum):
    ORIGINAL = "original"
    THUMBNAIL = "thumbnail"
    MEDIUM = "medium"
    LARGE = "large"
    SMALL = "small"


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

    # Relationships
    variants = db.relationship(
        "MediaVariant", back_populates="media", cascade="all, delete-orphan"
    )
    user = db.relationship("User", back_populates="media_uploads")

    def get_url(self, variant_type=MediaVariantType.ORIGINAL):
        # Implement your CDN URL generation logic
        return f"https://cdn.yourdomain.com/{self.storage_key}"


class MediaVariant(BaseModel):
    __tablename__ = "media_variants"

    id = db.Column(db.Integer, primary_key=True)
    media_id = db.Column(db.Integer, db.ForeignKey("media.id"))
    variant_type = db.Column(db.Enum(MediaVariantType))
    storage_key = db.Column(db.String(255))
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    file_size = db.Column(db.Integer)

    media = db.relationship("Media", back_populates="variants")


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
