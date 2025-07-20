import logging
import os
from typing import List, Dict, Any, Optional, Tuple
from io import BytesIO
from PIL import Image, ImageOps

from main.config import settings
from app.libs.aws.s3 import s3_service
from app.libs.session import session_scope
from .models import Media, MediaVariant, MediaType, MediaVariantType
from .errors import MediaUploadError, MediaProcessingError

logger = logging.getLogger(__name__)


class MediaService:
    """Comprehensive media service for handling uploads, processing, and variants"""

    def __init__(self):
        self.s3 = s3_service
        self.bucket = settings.AWS_S3_BUCKET

        # Essential variants (created immediately for all images)
        self.essential_variants = {
            MediaVariantType.THUMBNAIL: {"size": (150, 150), "quality": 80},
            MediaVariantType.SMALL: {"size": (300, 300), "quality": 85},
            MediaVariantType.MEDIUM: {"size": (600, 600), "quality": 85},
        }

        # On-demand variants (created when requested)
        self.on_demand_variants = {
            MediaVariantType.LARGE: {"size": (1200, 1200), "quality": 90},
            MediaVariantType.MOBILE: {"size": (400, 600), "quality": 85},
            MediaVariantType.TABLET: {"size": (800, 600), "quality": 85},
            MediaVariantType.DESKTOP: {"size": (1200, 800), "quality": 90},
            MediaVariantType.SOCIAL_SQUARE: {"size": (1080, 1080), "quality": 90},
            MediaVariantType.SOCIAL_STORY: {"size": (1080, 1920), "quality": 90},
            MediaVariantType.SOCIAL_POST: {"size": (1200, 630), "quality": 90},
        }

        # All variants (for backward compatibility)
        self.image_variants = {**self.essential_variants, **self.on_demand_variants}

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
    ) -> Media:
        """
        Upload image and queue async variant generation

        Args:
            file_stream: Image file stream
            filename: Original filename
            user_id: User ID
            alt_text: Alt text for accessibility
            caption: Image caption

        Returns:
            Media object (variants will be generated asynchronously)
        """
        try:
            logger.info(f"Starting image upload for {filename}")

            # Verify input stream
            if not file_stream or file_stream.getbuffer().nbytes == 0:
                raise MediaUploadError("Empty or invalid file stream provided")

            # Create a master copy of the file data
            file_stream.seek(0)
            file_data = file_stream.read()
            file_stream.seek(0)

            if not file_data:
                raise MediaUploadError("No data in file stream")

            # Create separate streams for each operation
            validation_stream = BytesIO(file_data)
            info_stream = BytesIO(file_data)
            upload_stream = BytesIO(file_data)

            # Validate file
            try:
                self._validate_image(validation_stream, filename)
            except Exception as e:
                logger.error(f"Image validation failed: {e}")
                raise MediaUploadError(f"Image validation failed: {str(e)}")
            finally:
                validation_stream.close()

            # Get image info
            try:
                with Image.open(info_stream) as img:
                    width, height = img.size
                    file_size = len(file_data)
            except Exception as e:
                logger.error(f"Failed to get image info: {e}")
                raise MediaUploadError(f"Failed to read image: {str(e)}")
            finally:
                info_stream.close()

            # Generate S3 key for original
            original_key = self.s3.generate_s3_key("images", filename, user_id=user_id)
            content_type = self.s3.get_content_type(filename)

            # Upload original to S3
            try:
                upload_stream.seek(0)
                original_url = self.s3.upload_fileobj(
                    upload_stream, str(self.bucket), original_key, content_type
                )
            except Exception as e:
                logger.error(f"S3 upload failed: {e}")
                raise MediaUploadError(f"S3 upload failed: {str(e)}")
            finally:
                upload_stream.close()

            # Create media record with session_scope
            try:
                with session_scope() as session:
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
                    media.processing_status = (
                        "uploaded"  # Will be updated by async task
                    )

                    session.add(media)
                    session.flush()  # This assigns the ID to media

                    # Queue async variant generation (essential variants only)
                    from .tasks import generate_media_variants

                    task_result = generate_media_variants.delay(
                        media.id, essential_only=True
                    )
                    logger.info(
                        f"Essential variant generation queued for media {media.id} (task: {task_result.id})"
                    )

                    # Return the media object (variants will be generated asynchronously)
                    return media
            except Exception as e:
                logger.error(f"Database operation failed: {e}")
                raise MediaUploadError(f"Database operation failed: {str(e)}")

        except Exception as e:
            logger.error(f"Failed to upload image {filename}: {e}", exc_info=True)
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
        Upload video file and queue async processing

        Args:
            file_stream: Video file stream
            filename: Original filename
            user_id: User ID
            alt_text: Alt text for accessibility
            caption: Video caption

        Returns:
            Media object (processing will be done asynchronously)
        """
        try:
            logger.info(f"Starting video upload for {filename}")

            # Validate video file
            self._validate_video(file_stream, filename)

            # Get file info
            file_size = file_stream.getbuffer().nbytes
            content_type = self.s3.get_content_type(filename)

            # Generate S3 key
            video_key = self.s3.generate_s3_key("videos", filename, user_id=user_id)

            # Upload video to S3
            file_stream.seek(0)
            video_url = self.s3.upload_fileobj(
                file_stream, str(self.bucket), video_key, content_type
            )

            logger.info(f"Video uploaded to S3: {video_key}")

            # Create media record with session_scope
            with session_scope() as session:
                media = Media()
                media.storage_key = video_key
                media.media_type = MediaType.VIDEO
                media.mime_type = content_type
                media.file_size = file_size
                media.alt_text = alt_text
                media.caption = caption
                media.user_id = user_id
                media.original_filename = filename
                media.processing_status = "uploaded"  # Will be updated by async task

                session.add(media)
                session.flush()  # This assigns the ID to media

                logger.info(f"Video media record created with ID: {media.id}")

                # Queue async video processing
                from .tasks import process_video_metadata

                process_video_metadata.delay(media.id)

                logger.info(f"Video processing queued for media {media.id}")

            return media

        except Exception as e:
            logger.error(f"Failed to upload video {filename}: {e}")
            raise MediaUploadError(f"Failed to upload video: {str(e)}")

    def _generate_image_variants_async(
        self, original_stream: BytesIO, filename: str, user_id: str, media: Media
    ) -> List[MediaVariant]:
        """
        Generate multiple image variants for different use cases (async version)

        This method is called by the Celery task and handles the actual variant generation

        Args:
            original_stream: Original image stream
            filename: Original filename
            user_id: User ID
            media: Media object

        Returns:
            List of MediaVariant objects
        """
        variants = []

        logger.info(f"Generating variants for media {media.id}")

        # Load the original image once and convert to RGB
        try:
            with Image.open(original_stream) as original_img:
                # Convert to RGB if necessary
                if original_img.mode in ("RGBA", "LA", "P"):
                    # Create white background for transparent images
                    background = Image.new("RGB", original_img.size, (255, 255, 255))
                    if original_img.mode == "P":
                        original_img = original_img.convert("RGBA")
                    background.paste(
                        original_img,
                        mask=original_img.split()[-1]
                        if original_img.mode == "RGBA"
                        else None,
                    )
                    original_img = background
                elif original_img.mode != "RGB":
                    original_img = original_img.convert("RGB")

                logger.info(
                    f"Original image loaded: {original_img.size} {original_img.mode}"
                )

        except Exception as e:
            logger.error(f"Failed to load original image: {e}")
            raise MediaProcessingError(f"Failed to load original image: {str(e)}")

        for variant_type, config in self.image_variants.items():
            try:
                logger.info(f"Generating variant: {variant_type.value}")

                # Create a fresh copy of the original image for this variant
                variant_img = original_img.copy()

                # Resize maintaining aspect ratio
                variant_img.thumbnail(config["size"], Image.Resampling.LANCZOS)

                # Save optimized image to BytesIO
                variant_stream = BytesIO()
                variant_img.save(
                    variant_stream,
                    format="JPEG",
                    quality=config["quality"],
                    optimize=True,
                )
                variant_stream.seek(0)

                # Generate S3 key for variant
                variant_key = self.s3.generate_s3_key(
                    "images", filename, variant=variant_type.value, user_id=user_id
                )

                # Upload variant to S3
                variant_url = self.s3.upload_fileobj(
                    variant_stream, str(self.bucket), variant_key, "image/jpeg"
                )

                logger.info(f"Variant uploaded to S3: {variant_key}")

                # Create MediaVariant record
                variant = MediaVariant()
                variant.media_id = media.id
                variant.variant_type = variant_type
                variant.storage_key = variant_key
                variant.width = variant_img.size[0]
                variant.height = variant_img.size[1]
                variant.file_size = variant_stream.getbuffer().nbytes
                variant.quality = config["quality"]
                variant.format = "JPEG"

                variants.append(variant)

                logger.info(f"Variant {variant_type.value} created: {variant_img.size}")

            except Exception as e:
                logger.error(f"Failed to generate variant {variant_type.value}: {e}")
                # Continue with other variants
                continue

        logger.info(f"Generated {len(variants)} variants for media {media.id}")
        return variants

    def _generate_essential_variants_async(
        self, original_stream: BytesIO, filename: str, user_id: str, media: Media
    ) -> List[MediaVariant]:
        """
        Generate only essential image variants for startup scalability

        This method generates only the most commonly used variants to reduce
        processing time and storage costs for startups.

        Args:
            original_stream: Original image stream
            filename: Original filename
            user_id: User ID
            media: Media object

        Returns:
            List of MediaVariant objects (essential variants only)
        """
        variants = []

        logger.info(f"Generating essential variants for media {media.id}")

        # Load the original image once and convert to RGB
        try:
            with Image.open(original_stream) as original_img:
                # Convert to RGB if necessary
                if original_img.mode in ("RGBA", "LA", "P"):
                    # Create white background for transparent images
                    background = Image.new("RGB", original_img.size, (255, 255, 255))
                    if original_img.mode == "P":
                        original_img = original_img.convert("RGBA")
                    background.paste(
                        original_img,
                        mask=original_img.split()[-1]
                        if original_img.mode == "RGBA"
                        else None,
                    )
                    original_img = background
                elif original_img.mode != "RGB":
                    original_img = original_img.convert("RGB")

                logger.info(
                    f"Original image loaded: {original_img.size} {original_img.mode}"
                )

        except Exception as e:
            logger.error(f"Failed to load original image: {e}")
            raise MediaProcessingError(f"Failed to load original image: {str(e)}")

        # Generate only essential variants
        for variant_type, config in self.essential_variants.items():
            try:
                logger.info(f"Generating essential variant: {variant_type.value}")

                # Create a fresh copy of the original image for this variant
                variant_img = original_img.copy()

                # Resize maintaining aspect ratio
                variant_img.thumbnail(config["size"], Image.Resampling.LANCZOS)

                # Save optimized image to BytesIO
                variant_stream = BytesIO()
                variant_img.save(
                    variant_stream,
                    format="JPEG",
                    quality=config["quality"],
                    optimize=True,
                )
                variant_stream.seek(0)

                # Generate S3 key for variant
                variant_key = self.s3.generate_s3_key(
                    "images", filename, variant=variant_type.value, user_id=user_id
                )

                # Upload variant to S3
                variant_url = self.s3.upload_fileobj(
                    variant_stream, str(self.bucket), variant_key, "image/jpeg"
                )

                logger.info(f"Essential variant uploaded to S3: {variant_key}")

                # Create MediaVariant record
                variant = MediaVariant()
                variant.media_id = media.id
                variant.variant_type = variant_type
                variant.storage_key = variant_key
                variant.width = variant_img.size[0]
                variant.height = variant_img.size[1]
                variant.file_size = variant_stream.getbuffer().nbytes
                variant.quality = config["quality"]
                variant.format = "JPEG"

                variants.append(variant)

                logger.info(
                    f"Essential variant {variant_type.value} created: {variant_img.size}"
                )

            except Exception as e:
                logger.error(
                    f"Failed to generate essential variant {variant_type.value}: {e}"
                )
                # Continue with other variants
                continue

        logger.info(
            f"Generated {len(variants)} essential variants for media {media.id}"
        )
        return variants

    def _generate_image_variants(
        self, original_stream: BytesIO, filename: str, user_id: str, media: Media
    ) -> List[MediaVariant]:
        """
        Generate multiple image variants for different use cases (synchronous version)

        This method is kept for backward compatibility but should not be used in production

        Args:
            original_stream: Original image stream
            filename: Original filename
            user_id: User ID
            media: Media object

        Returns:
            List of MediaVariant objects
        """
        logger.warning(
            "Using synchronous variant generation - this should be avoided in production"
        )
        return self._generate_image_variants_async(
            original_stream, filename, user_id, media
        )

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
        try:
            # Check file size
            file_size = file_stream.getbuffer().nbytes
            if file_size == 0:
                raise MediaUploadError("Empty file provided")

            if file_size > self.image_limits["max_size"]:
                raise MediaUploadError(
                    f"Image file too large. Max size: {self.image_limits['max_size']} bytes"
                )

            # Check file extension
            _, ext = os.path.splitext(filename.lower())
            if ext not in self.image_limits["allowed_formats"]:
                raise MediaUploadError(f"Unsupported image format: {ext}")

            # Validate image can be opened
            file_stream.seek(0)

            with Image.open(file_stream) as img:
                width, height = img.size
                if (
                    width > self.image_limits["max_dimensions"][0]
                    or height > self.image_limits["max_dimensions"][1]
                ):
                    raise MediaUploadError(
                        f"Image dimensions too large. Max: {self.image_limits['max_dimensions']}"
                    )

                # Verify it's actually an image
                if img.format not in ["JPEG", "PNG", "GIF", "WEBP"]:
                    raise MediaUploadError(f"Unsupported image format: {img.format}")

        except Exception as e:
            if isinstance(e, MediaUploadError):
                raise
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
        Checks if required variants exist and generates them on-demand if needed

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

        # Check if the target variant exists
        with session_scope() as session:
            existing_variant = (
                session.query(MediaVariant)
                .filter_by(media_id=media.id, variant_type=target_variant)
                .first()
            )

            if not existing_variant:
                logger.info(
                    f"Target variant {target_variant.value} not found for media {media.id}, generating on-demand"
                )
                try:
                    # Generate the required variant on-demand
                    self.generate_on_demand_variants(media.id, [target_variant])
                    logger.info(
                        f"Successfully generated on-demand variant {target_variant.value} for media {media.id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to generate on-demand variant {target_variant.value} for media {media.id}: {e}"
                    )
                    # Fall back to original URL if variant generation fails
                    return {
                        "optimized": media.get_url(),
                        "original": media.get_url(),
                        "platform": platform,
                        "post_type": post_type,
                        "note": f"Variant generation failed, using original image",
                    }

        return {
            "optimized": media.get_url(target_variant),
            "original": media.get_url(),
            "platform": platform,
            "post_type": post_type,
        }

    def generate_on_demand_variants(
        self, media_id: int, variant_types: List[MediaVariantType] = None
    ) -> List[MediaVariant]:
        """
        Generate on-demand variants for a media object

        Args:
            media_id: ID of the media object
            variant_types: List of variant types to generate (if None, generates all on-demand variants)

        Returns:
            List of generated MediaVariant objects
        """
        try:
            logger.info(f"Generating on-demand variants for media {media_id}")

            with session_scope() as session:
                # Get media object
                media = session.query(Media).get(media_id)
                if not media:
                    raise MediaProcessingError(f"Media {media_id} not found")

                # Get original image from S3
                original_stream = self.s3.download_fileobj(
                    str(self.bucket), media.storage_key
                )

                if not original_stream:
                    raise MediaProcessingError(
                        f"Failed to download original image for media {media_id}"
                    )

                # Determine which variants to generate
                if variant_types is None:
                    # Generate all on-demand variants
                    variants_to_generate = self.on_demand_variants
                else:
                    # Generate only specified variants
                    variants_to_generate = {
                        vt: self.on_demand_variants[vt]
                        for vt in variant_types
                        if vt in self.on_demand_variants
                    }

                # Check if variants already exist
                existing_variants = (
                    session.query(MediaVariant)
                    .filter(
                        MediaVariant.media_id == media_id,
                        MediaVariant.variant_type.in_(
                            [vt for vt in variants_to_generate.keys()]
                        ),
                    )
                    .all()
                )

                existing_types = {v.variant_type for v in existing_variants}
                missing_types = [
                    vt for vt in variants_to_generate.keys() if vt not in existing_types
                ]

                if not missing_types:
                    logger.info(
                        f"All requested variants already exist for media {media_id}"
                    )
                    return existing_variants

                # Generate missing variants
                variants = []
                for variant_type in missing_types:
                    config = variants_to_generate[variant_type]

                    try:
                        # Create variant
                        variant_stream = self._create_image_variant(
                            original_stream, config["size"], config["quality"]
                        )

                        # Generate S3 key
                        variant_key = self.s3.generate_s3_key(
                            "images",
                            media.original_filename,
                            variant=variant_type.value,
                            user_id=str(media.user_id),
                        )

                        # Upload to S3
                        self.s3.upload_fileobj(
                            variant_stream, str(self.bucket), variant_key, "image/jpeg"
                        )

                        # Create MediaVariant record
                        with Image.open(variant_stream) as img:
                            variant = MediaVariant()
                            variant.media_id = media_id
                            variant.variant_type = variant_type
                            variant.storage_key = variant_key
                            variant.width = img.size[0]
                            variant.height = img.size[1]
                            variant.file_size = variant_stream.getbuffer().nbytes
                            variant.quality = config["quality"]
                            variant.format = "JPEG"

                            session.add(variant)
                            variants.append(variant)

                        logger.info(
                            f"Generated on-demand variant {variant_type.value} for media {media_id}"
                        )

                    except Exception as e:
                        logger.error(
                            f"Failed to generate on-demand variant {variant_type.value}: {e}"
                        )
                        continue

                session.commit()
                logger.info(
                    f"Generated {len(variants)} on-demand variants for media {media_id}"
                )

                return variants + existing_variants

        except Exception as e:
            logger.error(
                f"Failed to generate on-demand variants for media {media_id}: {e}"
            )
            raise MediaProcessingError(
                f"Failed to generate on-demand variants: {str(e)}"
            )


# Global media service instance
media_service = MediaService()
