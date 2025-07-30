# python imports
import logging
from datetime import datetime, timedelta
from typing import Any, Dict
import json
from io import BytesIO

# project imports
from main.workers import celery_app
from external.redis import redis_client
from external.database import db
from app.libs.session import session_scope
from .errors import MediaProcessingError

# app imports
from .models import Media, MediaVariant, MediaType, MediaVariantType
from .services import MediaService
from app.users.models import User

logger = logging.getLogger(__name__)


def _update_user_profile_picture_url(media_id: int, user_id: str):
    """Helper function to update user profile picture URL after variant generation"""
    try:
        with session_scope() as session:
            # Get the media object
            media = session.query(Media).get(media_id)
            if not media:
                logger.error(f"Media {media_id} not found")
                return False

            # Get the user
            user = session.query(User).get(user_id)
            if not user:
                logger.error(f"User {user_id} not found")
                return False

            # Get the thumbnail URL
            thumbnail_url = media.get_url(MediaVariantType.THUMBNAIL)

            # Update user profile picture
            user.profile_picture = thumbnail_url
            session.commit()

            logger.info(
                f"Updated profile picture URL for user {user_id}: {thumbnail_url}"
            )
            return True

    except Exception as e:
        logger.error(f"Failed to update profile picture URL: {e}")
        return False


@celery_app.task(bind=True, max_retries=3, queue="media")
def generate_media_variants(
    self, media_id: int, essential_only: bool = False, profile_picture: bool = False
):
    """
    Generate image variants for a media object asynchronously

    Args:
        media_id: ID of the media object to process
        essential_only: If True, only generate essential variants (for startup scalability)
    """
    try:
        logger.info(
            f"Starting variant generation for media {media_id} (essential_only: {essential_only})"
        )

        with session_scope() as session:
            # Get media object
            media = session.query(Media).get(media_id)
            if not media:
                raise MediaProcessingError(f"Media {media_id} not found")

            # Update status to processing
            media.processing_status = "processing"
            session.flush()
            logger.info(f"Updated media {media_id} status to processing")

            # Get original image from S3
            logger.info(f"Downloading original image for media {media_id}")
            media_service = MediaService()

            try:
                original_stream = media_service.s3.download_fileobj(
                    str(media_service.bucket), media.storage_key
                )
                logger.info(
                    f"Successfully downloaded original image for media {media_id}"
                )
            except Exception as download_error:
                logger.error(
                    f"Failed to download original image for media {media_id}: {download_error}"
                )
                raise MediaProcessingError(
                    f"Failed to download original image: {str(download_error)}"
                )

            if not original_stream:
                raise MediaProcessingError(
                    f"Downloaded stream is empty for media {media_id}"
                )

            # Generate variants (essential only or all)
            if profile_picture:
                logger.info(f"Generating profile picture variants for media {media_id}")
                variants = media_service._generate_profile_picture_variants_async(
                    original_stream, media.original_filename, str(media.user_id), media
                )
            elif essential_only:
                logger.info(f"Generating essential variants only for media {media_id}")
                variants = media_service._generate_essential_variants_async(
                    original_stream, media.original_filename, str(media.user_id), media
                )
            else:
                logger.info(f"Generating all variants for media {media_id}")
                variants = media_service._generate_image_variants_async(
                    original_stream, media.original_filename, str(media.user_id), media
                )

            # Save variants to database
            logger.info(
                f"Saving {len(variants)} variants to database for media {media_id}"
            )
            for variant in variants:
                variant.media_id = media.id
                session.add(variant)

            # Update media status to completed
            media.processing_status = "completed"
            session.flush()

            logger.info(
                f"Successfully generated {len(variants)} variants for media {media_id}"
            )

            # Cache the media URLs for faster access
            try:
                urls = media_service.get_media_urls(media, include_variants=True)
                cache_key = f"media:urls:{media_id}"
                redis_client.setex(
                    cache_key, 3600, json.dumps(urls)
                )  # Cache for 1 hour
                logger.info(f"Cached media URLs for media {media_id}")
            except Exception as cache_error:
                logger.warning(f"Failed to cache media URLs: {cache_error}")

            # If this is a profile picture, update the user's profile picture URL
            if profile_picture:
                _update_user_profile_picture_url(media_id, str(media.user_id))
                logger.info(
                    f"Queued profile picture URL update for user {media.user_id}"
                )

            return {
                "media_id": media_id,
                "variants_generated": len(variants),
                "processing_status": media.processing_status,
            }

    except Exception as e:
        logger.error(
            f"Failed to generate variants for media {media_id}: {str(e)}", exc_info=True
        )

        # Update status to failed
        try:
            with session_scope() as session:
                media = session.query(Media).get(media_id)
                if media:
                    media.processing_status = "failed"
                    media.processing_error = str(e)
                    session.flush()
                    logger.info(f"Updated media {media_id} status to failed")
        except Exception as update_error:
            logger.error(f"Failed to update media status: {update_error}")

        # Retry logic with exponential backoff
        if self.request.retries < self.max_retries:
            logger.info(
                f"Retrying variant generation for media {media_id} (attempt {self.request.retries + 1})"
            )
            raise self.retry(countdown=60 * (2**self.request.retries))

        raise MediaProcessingError(
            f"Failed to generate variants after {self.max_retries} attempts: {str(e)}"
        )


@celery_app.task(bind=True, max_retries=3, queue="media")
def process_media_upload(
    self, media_id: int, processing_options: Dict[str, Any] = None
):
    """
    Process media upload with background tasks

    Args:
        media_id: ID of the media object to process
        processing_options: Optional processing options
    """
    try:
        logger.info(f"Starting media processing for media {media_id}")

        with session_scope() as session:
            media = session.query(Media).get(media_id)
            if not media:
                raise MediaProcessingError(f"Media {media_id} not found")

            # Update status to processing
            media.processing_status = "processing"
            session.flush()

            # Process based on media type
            if media.media_type == MediaType.IMAGE:
                # Generate variants asynchronously
                generate_media_variants.delay(media_id)

                # Handle background removal if requested
                if processing_options and processing_options.get("remove_background"):
                    remove_background_from_image.delay(media_id)

            elif media.media_type == MediaType.VIDEO:
                # Process video (placeholder for future implementation)
                process_video_metadata.delay(media_id)

            logger.info(f"Media processing initiated for media {media_id}")

            return {
                "media_id": media_id,
                "status": "processing_initiated",
                "message": "Media processing started in background",
            }

    except Exception as e:
        logger.error(f"Failed to process media {media_id}: {str(e)}")

        # Update status to failed
        try:
            with session_scope() as session:
                media = session.query(Media).get(media_id)
                if media:
                    media.processing_status = "failed"
                    media.processing_error = str(e)
                    session.flush()
        except Exception as update_error:
            logger.error(f"Failed to update media status: {update_error}")

        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30 * (2**self.request.retries))

        raise MediaProcessingError(
            f"Failed to process media after {self.max_retries} attempts: {str(e)}"
        )


@celery_app.task(bind=True, queue="media")
def remove_background_from_image(self, media_id: int):
    """
    Remove background from image (placeholder for future implementation)

    Args:
        media_id: ID of the media object to process
    """
    try:
        logger.info(
            f"Background removal requested for media {media_id} (not implemented yet)"
        )

        # TODO: Implement background removal using removebg API or similar
        # For now, just mark as processed

        with session_scope() as session:
            media = session.query(Media).get(media_id)
            if media:
                media.processing_status = "completed"
                session.flush()

        return {
            "media_id": media_id,
            "status": "background_removal_completed",
            "message": "Background removal completed (placeholder)",
        }

    except Exception as e:
        logger.error(f"Background removal failed for media {media_id}: {str(e)}")
        raise MediaProcessingError(f"Background removal failed: {str(e)}")


@celery_app.task(bind=True, queue="media")
def process_video_metadata(self, media_id: int):
    """
    Process video metadata for MVP

    Args:
        media_id: ID of the media object to process
    """
    try:
        logger.info(f"Processing video metadata for media {media_id}")

        with session_scope() as session:
            media = session.query(Media).get(media_id)
            if not media:
                raise MediaProcessingError(f"Media {media_id} not found")

            # Update status to processing
            media.processing_status = "processing"
            session.flush()

            # Get video from S3
            media_service = MediaService()
            try:
                video_stream = media_service.s3.download_fileobj(
                    str(media_service.bucket), media.storage_key
                )
                logger.info(f"Downloaded video for metadata extraction: {media_id}")
            except Exception as download_error:
                logger.error(f"Failed to download video {media_id}: {download_error}")
                raise MediaProcessingError(
                    f"Failed to download video: {str(download_error)}"
                )

            # Extract basic metadata using ffmpeg-python
            try:
                import ffmpeg
                import tempfile
                import os

                # Save video to temporary file for ffmpeg processing
                with tempfile.NamedTemporaryFile(
                    suffix=".mp4", delete=False
                ) as temp_file:
                    temp_file.write(video_stream.read())
                    temp_file_path = temp_file.name

                try:
                    # Extract video metadata
                    probe = ffmpeg.probe(temp_file_path)
                    video_info = next(
                        s for s in probe["streams"] if s["codec_type"] == "video"
                    )

                    # Extract duration
                    duration = float(probe["format"]["duration"])
                    media.duration = int(duration)

                    # Extract resolution
                    media.width = int(video_info["width"])
                    media.height = int(video_info["height"])

                    logger.info(
                        f"Extracted metadata for video {media_id}: {media.width}x{media.height}, {duration}s"
                    )

                    # Generate thumbnail
                    thumbnail_path = temp_file_path.replace(".mp4", "_thumb.jpg")
                    try:
                        ffmpeg.input(temp_file_path, ss="00:00:01").output(
                            thumbnail_path,
                            vframes=1,
                            vf="scale=320:240:force_original_aspect_ratio=decrease",
                            acodec="none",
                        ).overwrite_output().run(
                            capture_stdout=True, capture_stderr=True
                        )

                        # Upload thumbnail to S3
                        with open(thumbnail_path, "rb") as thumb_file:
                            thumbnail_key = media_service.s3.generate_s3_key(
                                "thumbnails",
                                f"{media.id}_thumb.jpg",
                                user_id=media.user_id,
                            )
                            # Convert file object to BytesIO for S3 upload
                            thumb_data = thumb_file.read()
                            thumb_stream = BytesIO(thumb_data)
                            media_service.s3.upload_fileobj(
                                thumb_stream,
                                str(media_service.bucket),
                                thumbnail_key,
                                "image/jpeg",
                            )

                        # Create thumbnail variant record
                        thumbnail_variant = MediaVariant(
                            media_id=media.id,
                            variant_type=MediaVariantType.THUMBNAIL,
                            storage_key=thumbnail_key,
                            width=320,
                            height=240,
                            file_size=os.path.getsize(thumbnail_path),
                        )
                        session.add(thumbnail_variant)

                        logger.info(f"Generated thumbnail for video {media_id}")

                        # Clean up thumbnail file
                        os.unlink(thumbnail_path)

                    except Exception as thumb_error:
                        logger.warning(
                            f"Failed to generate thumbnail for video {media_id}: {thumb_error}"
                        )
                        # Continue without thumbnail - not critical for MVP

                finally:
                    # Clean up temporary video file
                    os.unlink(temp_file_path)

            except Exception as metadata_error:
                logger.error(
                    f"Failed to extract video metadata for {media_id}: {metadata_error}"
                )
                # For MVP, continue without metadata rather than failing completely

            # Update status to completed
            media.processing_status = "completed"
            session.flush()

            logger.info(f"Video metadata processing completed for media {media_id}")

            return {
                "media_id": media_id,
                "status": "video_processing_completed",
                "duration": media.duration,
                "width": media.width,
                "height": media.height,
                "message": "Video processing completed successfully",
            }

    except Exception as e:
        logger.error(f"Video processing failed for media {media_id}: {str(e)}")

        # Update status to failed
        try:
            with session_scope() as session:
                media = session.query(Media).get(media_id)
                if media:
                    media.processing_status = "failed"
                    media.processing_error = str(e)
                    session.flush()
        except Exception as update_error:
            logger.error(f"Failed to update media status: {update_error}")

        raise MediaProcessingError(f"Video processing failed: {str(e)}")


@celery_app.task(bind=True, queue="media")
def cleanup_failed_media(self):
    """
    Clean up media objects that failed processing
    """
    try:
        with session_scope() as session:
            # Find media that failed processing more than 24 hours ago
            cutoff_time = datetime.utcnow() - timedelta(hours=24)

            failed_media = (
                session.query(Media)
                .filter(
                    Media.processing_status == "failed", Media.created_at < cutoff_time
                )
                .all()
            )

            cleaned_count = 0
            for media in failed_media:
                try:
                    # Delete from S3
                    media_service = MediaService()
                    media_service.delete_media(media)

                    # Delete from database
                    session.delete(media)
                    cleaned_count += 1

                except Exception as e:
                    logger.error(f"Failed to cleanup media {media.id}: {str(e)}")
                    continue

            session.flush()

            logger.info(f"Cleaned up {cleaned_count} failed media objects")

            return {"cleaned_count": cleaned_count, "status": "cleanup_completed"}

    except Exception as e:
        logger.error(f"Media cleanup failed: {str(e)}")
        raise MediaProcessingError(f"Media cleanup failed: {str(e)}")


@celery_app.task(bind=True, queue="media")
def cleanup_orphaned_media(self):
    """
    Clean up orphaned media records (uploaded but never processed)
    """
    try:
        with session_scope() as session:
            # Find media that was uploaded but never processed (older than 1 hour)
            cutoff_time = datetime.utcnow() - timedelta(hours=1)

            orphaned_media = (
                session.query(Media)
                .filter(
                    Media.processing_status == "uploaded",
                    Media.created_at < cutoff_time,
                )
                .all()
            )

            cleaned_count = 0
            for media in orphaned_media:
                try:
                    logger.info(
                        f"Cleaning up orphaned media {media.id} (uploaded but never processed)"
                    )

                    # Delete from S3
                    media_service = MediaService()
                    media_service.delete_media(media)

                    # Delete from database
                    session.delete(media)
                    cleaned_count += 1

                except Exception as e:
                    logger.error(
                        f"Failed to cleanup orphaned media {media.id}: {str(e)}"
                    )
                    continue

            session.flush()

            logger.info(f"Cleaned up {cleaned_count} orphaned media objects")

            return {
                "cleaned_count": cleaned_count,
                "status": "orphaned_cleanup_completed",
            }

    except Exception as e:
        logger.error(f"Orphaned media cleanup failed: {str(e)}")
        raise MediaProcessingError(f"Orphaned media cleanup failed: {str(e)}")


@celery_app.task(bind=True, queue="media")
def update_media_analytics(self):
    """
    Update media analytics and statistics
    """
    try:
        with session_scope() as session:
            # Calculate media statistics
            total_media = session.query(Media).count()
            total_images = (
                session.query(Media).filter(Media.media_type == MediaType.IMAGE).count()
            )
            total_videos = (
                session.query(Media).filter(Media.media_type == MediaType.VIDEO).count()
            )

            # Calculate storage usage
            total_size = session.query(db.func.sum(Media.file_size)).scalar() or 0

            # Calculate processing statistics
            processing_stats = (
                session.query(Media.processing_status, db.func.count(Media.id))
                .group_by(Media.processing_status)
                .all()
            )

            analytics = {
                "total_media": total_media,
                "total_images": total_images,
                "total_videos": total_videos,
                "total_size_bytes": total_size,
                "processing_stats": dict(processing_stats),
                "last_updated": datetime.utcnow().isoformat(),
            }

            # Cache analytics for 1 hour
            redis_client.setex("media:analytics", 3600, str(analytics))

            logger.info("Updated media analytics")

            return analytics

    except Exception as e:
        logger.error(f"Media analytics update failed: {str(e)}")
        raise MediaProcessingError(f"Media analytics update failed: {str(e)}")


@celery_app.task(bind=True, queue="media")
def cleanup_soft_deleted_media(self, retention_days: int = 30):
    """
    Clean up soft-deleted media after retention period.

    This task permanently deletes media that has been soft-deleted for longer
    than the specified retention period. It keeps the lightest weight variant
    (usually thumbnail) for potential recovery.

    Args:
        retention_days: Number of days to keep soft-deleted media before permanent deletion
    """
    try:
        with session_scope() as session:
            # Find media that was soft-deleted before the cutoff time
            cutoff_time = datetime.utcnow() - timedelta(days=retention_days)

            soft_deleted_media = (
                session.query(Media)
                .filter(
                    Media.deleted_at.isnot(None),
                    Media.deleted_at < cutoff_time,
                )
                .all()
            )

            cleaned_count = 0
            for media in soft_deleted_media:
                try:
                    logger.info(
                        f"Permanently deleting soft-deleted media {media.id} "
                        f"(deleted on {media.deleted_at})"
                    )

                    # Keep the lightest weight variant (usually thumbnail)
                    variants_to_keep = []
                    if hasattr(media, "variants") and media.variants:
                        # Sort variants by file size and keep the smallest
                        sorted_variants = sorted(
                            media.variants, key=lambda v: v.file_size or 0
                        )
                        if sorted_variants:
                            variants_to_keep = [
                                sorted_variants[0]
                            ]  # Keep smallest variant

                            # Delete other variants from S3
                            for variant in sorted_variants[1:]:
                                media_service = MediaService()
                                media_service.s3.delete_file(
                                    str(media_service.bucket), variant.storage_key
                                )
                                session.delete(variant)

                    # Delete original from S3
                    media_service = MediaService()
                    media_service.s3.delete_file(
                        str(media_service.bucket), media.storage_key
                    )

                    # Delete media record from database
                    session.delete(media)
                    cleaned_count += 1

                except Exception as e:
                    logger.error(
                        f"Failed to cleanup soft-deleted media {media.id}: {str(e)}"
                    )
                    continue

            session.flush()

            logger.info(f"Cleaned up {cleaned_count} soft-deleted media objects")

            return {
                "cleaned_count": cleaned_count,
                "retention_days": retention_days,
                "status": "soft_delete_cleanup_completed",
            }

    except Exception as e:
        logger.error(f"Soft-deleted media cleanup failed: {str(e)}")
        raise MediaProcessingError(f"Soft-deleted media cleanup failed: {str(e)}")
