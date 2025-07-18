import logging
import os
from typing import List, Dict, Any, Optional, Tuple
from io import BytesIO
from PIL import Image, ImageOps

from main.config import settings
from app.libs.aws.s3 import s3_service
from .models import Media, MediaVariant, MediaType, MediaVariantType
from .errors import MediaUploadError, MediaProcessingError

logger = logging.getLogger(__name__)


class MediaService:
    """Comprehensive media service for handling uploads, processing, and variants"""

    def __init__(self):
        self.s3 = s3_service
        self.bucket = settings.AWS_S3_BUCKET

        # Image variant configurations
        self.image_variants = {
            MediaVariantType.THUMBNAIL: {"size": (150, 150), "quality": 80},
            MediaVariantType.SMALL: {"size": (300, 300), "quality": 85},
            MediaVariantType.MEDIUM: {"size": (600, 600), "quality": 85},
            MediaVariantType.LARGE: {"size": (1200, 1200), "quality": 90},
            MediaVariantType.MOBILE: {"size": (400, 600), "quality": 85},
            MediaVariantType.TABLET: {"size": (800, 600), "quality": 85},
            MediaVariantType.DESKTOP: {"size": (1200, 800), "quality": 90},
            MediaVariantType.SOCIAL_SQUARE: {"size": (1080, 1080), "quality": 90},
            MediaVariantType.SOCIAL_STORY: {"size": (1080, 1920), "quality": 90},
            MediaVariantType.SOCIAL_POST: {"size": (1200, 630), "quality": 90},
        }

        # Video size limits (in bytes)
        self.video_limits = {
            "max_size": 100 * 1024 * 1024,  # 100MB
            "max_duration": 300,  # 5 minutes
            "allowed_formats": [".mp4", ".mov", ".avi", ".mkv"],
        }

        # Image size limits
        self.image_limits = {
            "max_size": 10 * 1024 * 1024,  # 10MB
            "max_dimensions": (4000, 4000),
            "allowed_formats": [".jpg", ".jpeg", ".png", ".webp", ".gif"],
        }

    def upload_image(
        self,
        file_stream: BytesIO,
        filename: str,
        user_id: str,
        alt_text: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> Tuple[Media, List[MediaVariant]]:
        """
        Upload and process image with multiple variants

        Args:
            file_stream: Image file stream
            filename: Original filename
            user_id: User ID
            alt_text: Alt text for accessibility
            caption: Image caption

        Returns:
            Tuple of (Media, List[MediaVariant])
        """
        try:
            # Validate file
            self._validate_image(file_stream, filename)

            # Get image info
            with Image.open(file_stream) as img:
                width, height = img.size
                file_size = file_stream.getbuffer().nbytes

            # Generate S3 key for original
            original_key = self.s3.generate_s3_key("images", filename, user_id=user_id)
            content_type = self.s3.get_content_type(filename)

            # Upload original
            file_stream.seek(0)
            original_url = self.s3.upload_fileobj(
                file_stream, str(self.bucket), original_key, content_type
            )

            # Create media record
            media = Media()
            media.storage_key = original_key
            media.media_type = MediaType.IMAGE
            media.mime_type = content_type
            media.width = width
            media.height = height
            media.file_size = file_size
            media.alt_text = alt_text
            media.caption = caption
            media.user_id = user_id
            media.original_filename = filename
            media.processing_status = "completed"

            # Generate variants
            variants = self._generate_image_variants(
                file_stream, filename, user_id, media
            )

            return media, variants

        except Exception as e:
            logger.error(f"Failed to upload image {filename}: {e}")
            raise MediaUploadError(f"Failed to upload image: {str(e)}")

    def upload_video(
        self,
        file_stream: BytesIO,
        filename: str,
        user_id: str,
        alt_text: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> Media:
        """
        Upload video file (MVP - limited processing)

        Args:
            file_stream: Video file stream
            filename: Original filename
            user_id: User ID
            alt_text: Alt text for accessibility
            caption: Video caption

        Returns:
            Media object
        """
        try:
            # Validate video file
            self._validate_video(file_stream, filename)

            # Get file info
            file_size = file_stream.getbuffer().nbytes
            content_type = self.s3.get_content_type(filename)

            # Generate S3 key
            video_key = self.s3.generate_s3_key("videos", filename, user_id=user_id)

            # Upload video
            file_stream.seek(0)
            video_url = self.s3.upload_fileobj(
                file_stream, str(self.bucket), video_key, content_type
            )

            # Create media record (duration will be updated later if needed)
            media = Media()
            media.storage_key = video_key
            media.media_type = MediaType.VIDEO
            media.mime_type = content_type
            media.file_size = file_size
            media.alt_text = alt_text
            media.caption = caption
            media.user_id = user_id
            media.original_filename = filename
            media.processing_status = "completed"

            return media

        except Exception as e:
            logger.error(f"Failed to upload video {filename}: {e}")
            raise MediaUploadError(f"Failed to upload video: {str(e)}")

    def _generate_image_variants(
        self, original_stream: BytesIO, filename: str, user_id: str, media: Media
    ) -> List[MediaVariant]:
        """
        Generate multiple image variants for different use cases

        Args:
            original_stream: Original image stream
            filename: Original filename
            user_id: User ID
            media: Media object

        Returns:
            List of MediaVariant objects
        """
        variants = []

        for variant_type, config in self.image_variants.items():
            try:
                # Create variant
                variant_stream = self._create_image_variant(
                    original_stream, config["size"], config["quality"]
                )

                # Generate S3 key for variant
                variant_key = self.s3.generate_s3_key(
                    "images", filename, variant=variant_type.value, user_id=user_id
                )

                # Upload variant
                variant_stream.seek(0)
                variant_url = self.s3.upload_fileobj(
                    variant_stream, str(self.bucket), variant_key, "image/jpeg"
                )

                # Get variant dimensions
                with Image.open(variant_stream) as img:
                    width, height = img.size

                # Create MediaVariant record
                variant = MediaVariant()
                variant.media_id = media.id
                variant.variant_type = variant_type
                variant.storage_key = variant_key
                variant.width = width
                variant.height = height
                variant.file_size = variant_stream.getbuffer().nbytes
                variant.quality = config["quality"]
                variant.format = "JPEG"

                variants.append(variant)

            except Exception as e:
                logger.error(f"Failed to generate variant {variant_type.value}: {e}")
                # Continue with other variants
                continue

        return variants

    def _create_image_variant(
        self, image_stream: BytesIO, size: Tuple[int, int], quality: int
    ) -> BytesIO:
        """
        Create an image variant with specified size and quality

        Args:
            image_stream: Original image stream
            size: Target size (width, height)
            quality: JPEG quality (1-100)

        Returns:
            Optimized image as BytesIO
        """
        try:
            with Image.open(image_stream) as img:
                # Convert to RGB if necessary
                if img.mode in ("RGBA", "LA", "P"):
                    # Create white background for transparent images
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    background.paste(
                        img, mask=img.split()[-1] if img.mode == "RGBA" else None
                    )
                    img = background
                elif img.mode != "RGB":
                    img = img.convert("RGB")

                # Resize maintaining aspect ratio
                img.thumbnail(size, Image.Resampling.LANCZOS)

                # Save optimized image
                output = BytesIO()
                img.save(output, format="JPEG", quality=quality, optimize=True)
                output.seek(0)
                return output

        except Exception as e:
            logger.error(f"Failed to create image variant: {e}")
            raise MediaProcessingError(f"Failed to create image variant: {str(e)}")

    def remove_background(self, media_id: int) -> bool:
        """
        Remove background from image (placeholder for future implementation)

        Args:
            media_id: Media ID

        Returns:
            True if successful
        """
        # TODO: Implement background removal using removebg API or similar
        # For now, just mark as processed
        logger.info(
            f"Background removal requested for media {media_id} (not implemented yet)"
        )
        return True

    def _validate_image(self, file_stream: BytesIO, filename: str):
        """Validate image file"""
        # Check file size
        file_size = file_stream.getbuffer().nbytes
        if file_size > self.image_limits["max_size"]:
            raise MediaUploadError(
                f"Image file too large. Max size: {self.image_limits['max_size']} bytes"
            )

        # Check file extension
        _, ext = os.path.splitext(filename.lower())
        if ext not in self.image_limits["allowed_formats"]:
            raise MediaUploadError(f"Unsupported image format: {ext}")

        # Validate image can be opened
        try:
            with Image.open(file_stream) as img:
                width, height = img.size
                if (
                    width > self.image_limits["max_dimensions"][0]
                    or height > self.image_limits["max_dimensions"][1]
                ):
                    raise MediaUploadError(
                        f"Image dimensions too large. Max: {self.image_limits['max_dimensions']}"
                    )
        except Exception as e:
            raise MediaUploadError(f"Invalid image file: {str(e)}")

    def _validate_video(self, file_stream: BytesIO, filename: str):
        """Validate video file"""
        # Check file size
        file_size = file_stream.getbuffer().nbytes
        if file_size > self.video_limits["max_size"]:
            raise MediaUploadError(
                f"Video file too large. Max size: {self.video_limits['max_size']} bytes"
            )

        # Check file extension
        _, ext = os.path.splitext(filename.lower())
        if ext not in self.video_limits["allowed_formats"]:
            raise MediaUploadError(f"Unsupported video format: {ext}")

    def delete_media(self, media: Media) -> bool:
        """
        Delete media and all its variants from S3 and database

        Args:
            media: Media object to delete

        Returns:
            True if successful
        """
        try:
            # Delete original
            self.s3.delete_file(str(self.bucket), media.storage_key)

            # Delete variants
            if hasattr(media, "variants") and media.variants:
                for variant in media.variants:
                    self.s3.delete_file(str(self.bucket), variant.storage_key)

            return True

        except Exception as e:
            logger.error(f"Failed to delete media {media.id}: {e}")
            return False

    def get_media_urls(
        self, media: Media, include_variants: bool = True
    ) -> Dict[str, Any]:
        """
        Get all URLs for a media object

        Args:
            media: Media object
            include_variants: Whether to include variant URLs

        Returns:
            Dictionary with URLs
        """
        urls = {
            "original": media.get_url(),
            "type": media.media_type.value,
            "mime_type": media.mime_type,
        }

        if include_variants and hasattr(media, "variants") and media.variants:
            urls["variants"] = {}
            for variant in media.variants:
                urls["variants"][variant.variant_type.value] = {
                    "url": variant.get_url(),
                    "width": variant.width,
                    "height": variant.height,
                    "file_size": variant.file_size,
                }

        return urls

    def optimize_for_social_media(
        self, media: Media, platform: str, post_type: str
    ) -> Dict[str, str]:
        """
        Get optimized URLs for social media platforms

        Args:
            media: Media object
            platform: Social media platform (instagram, facebook, twitter)
            post_type: Post type (story, post, reel)

        Returns:
            Dictionary with optimized URLs
        """
        if media.media_type != MediaType.IMAGE:
            return {"original": media.get_url()}

        # Map platform and post type to variant
        variant_mapping = {
            "instagram": {
                "story": MediaVariantType.SOCIAL_STORY,
                "post": MediaVariantType.SOCIAL_SQUARE,
                "reel": MediaVariantType.SOCIAL_STORY,
            },
            "facebook": {
                "post": MediaVariantType.SOCIAL_POST,
                "story": MediaVariantType.SOCIAL_STORY,
            },
            "twitter": {"post": MediaVariantType.SOCIAL_POST},
        }

        target_variant = variant_mapping.get(platform, {}).get(
            post_type, MediaVariantType.MEDIUM
        )

        return {
            "optimized": media.get_url(target_variant),
            "original": media.get_url(),
            "platform": platform,
            "post_type": post_type,
        }


# Global media service instance
media_service = MediaService()
