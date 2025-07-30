import logging
import time
from io import BytesIO

from flask import request, current_app
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import and_, or_, desc, func

from external.database import db
from app.libs.decorators import admin_required
from app.libs.pagination import Paginator
from app.libs.session import session_scope
from .models import (
    Media,
    MediaVariant,
    MediaType,
    MediaVariantType,
    ProductImage,
    SocialMediaPost,
)
from .schemas import (
    MediaSchema,
    MediaUploadSchema,
    MediaUploadResponseSchema,
    MediaListSchema,
    MediaFilterSchema,
    SocialMediaOptimizationSchema,
    SocialMediaOptimizationResponseSchema,
    ProductImageSchema,
    SocialMediaPostSchema,
    MediaDeleteSchema,
    MediaStatsSchema,
    RequestImageSchema,
)
from .services import media_service
from .errors import MediaUploadError, MediaProcessingError

logger = logging.getLogger(__name__)

# Create blueprint
bp = Blueprint(
    "media", __name__, description="Media management operations", url_prefix="/media"
)


@bp.route("/upload")
class MediaUpload(MethodView):
    @login_required
    @bp.response(201, MediaUploadResponseSchema)
    @bp.alt_response(400, description="Invalid file or validation error")
    @bp.alt_response(413, description="File too large")
    @bp.alt_response(415, description="Unsupported file type")
    def post(self):
        """
        Upload media file (image or video)

        Supports:
        - Image upload with automatic variant generation
        - Video upload (MVP - limited processing)
        - Background removal placeholder
        - Social media optimization
        - Responsive variants for different screen sizes
        """
        media = None
        file_stream = None

        try:
            # Check if file is present
            if "file" not in request.files:
                abort(400, message="No file provided")

            file = request.files["file"]
            if file.filename == "":
                abort(400, message="No file selected")

            # Validate file
            filename = secure_filename(file.filename)
            if not filename:
                abort(400, message="Invalid filename")

            logger.info(f"Starting upload for file: {filename}")

            # Track upload start time
            start_time = time.time()

            # Read file into memory with timeout protection
            try:
                # Read file data with a reasonable timeout
                file_data = file.read()
                if not file_data:
                    abort(400, message="Empty file provided")
            except (OSError, IOError) as read_error:
                logger.warning(f"File read interrupted for {filename}: {read_error}")
                abort(499, message="Request cancelled by client")
            except Exception as read_error:
                logger.error(f"Failed to read file {filename}: {read_error}")
                abort(400, message="Failed to read file")

            file_stream = BytesIO(file_data)
            file_size = len(file_data)

            # Verify the stream is valid
            if file_stream.getbuffer().nbytes != file_size:
                abort(400, message="File stream corrupted")

            # Get current user
            user_id = str(current_user.id)

            # Determine media type
            content_type = file.content_type or media_service.s3.get_content_type(
                filename
            )
            media_type = None

            if content_type.startswith("image/"):
                media_type = MediaType.IMAGE
            elif content_type.startswith("video/"):
                media_type = MediaType.VIDEO
            else:
                abort(415, message="Unsupported file type")

            # Get form data
            alt_text = request.form.get("alt_text")
            caption = request.form.get("caption")
            is_public = request.form.get("is_public", "true").lower() == "true"
            remove_background = (
                request.form.get("remove_background", "false").lower() == "true"
            )
            int(request.form.get("compression_quality", 85))
            optimize_for_social = (
                request.form.get("optimize_for_social", "true").lower() == "true"
            )

            # Upload based on media type with timeout protection
            try:
                if media_type == MediaType.IMAGE:
                    media = media_service.upload_image(
                        file_stream=file_stream,
                        filename=filename,
                        user_id=user_id,
                        alt_text=alt_text,
                        caption=caption,
                    )
                else:  # Video
                    media = media_service.upload_video(
                        file_stream=file_stream,
                        filename=filename,
                        user_id=user_id,
                        alt_text=alt_text,
                        caption=caption,
                    )
            except (OSError, IOError) as upload_error:
                logger.warning(f"Upload interrupted for {filename}: {upload_error}")
                abort(499, message="Request cancelled by client")
            except Exception as upload_error:
                logger.error(f"Upload failed for {filename}: {upload_error}")
                raise upload_error

            # Get basic URLs (original only, variants will be available later)
            urls = media_service.get_media_urls(media, include_variants=False)

            # Background removal placeholder
            if remove_background and media_type == MediaType.IMAGE:
                logger.info(
                    f"Background removal requested for media {media.id} (not implemented yet)"
                )

            upload_time = time.time() - start_time
            logger.info(f"Upload completed in {upload_time:.2f} seconds")

            return {
                "success": True,
                "media": {
                    "id": media.id,
                    "storage_key": media.storage_key,
                    "media_type": media.media_type,
                    "mime_type": media.mime_type,
                    "width": media.width,
                    "height": media.height,
                    "file_size": media.file_size,
                    "alt_text": media.alt_text,
                    "caption": media.caption,
                    "original_filename": media.original_filename,
                    "processing_status": media.processing_status,
                    "created_at": media.created_at,
                },
                "variants": [],  # Variants will be generated asynchronously
                "urls": urls,
                "upload_time": upload_time,
                "message": f"Successfully uploaded {media_type.value}. Variants are being generated in the background.",
                "processing_note": "Image variants are being generated asynchronously and will be available shortly.",
            }

        except MediaUploadError as e:
            logger.error(f"Media upload error: {e}")
            # Clean up any partial uploads
            if media:
                try:
                    media_service.delete_media(media)
                    logger.info(f"Cleaned up failed media {media.id}")
                except Exception as cleanup_error:
                    logger.error(
                        f"Failed to cleanup failed media {media.id}: {cleanup_error}"
                    )
            abort(400, message=str(e))

        except MediaProcessingError as e:
            logger.error(f"Media processing error: {e}")
            # Clean up any partial uploads
            if media:
                try:
                    media_service.delete_media(media)
                    logger.info(f"Cleaned up failed media {media.id}")
                except Exception as cleanup_error:
                    logger.error(
                        f"Failed to cleanup failed media {media.id}: {cleanup_error}"
                    )
            abort(500, message=str(e))

        except Exception as e:
            logger.error(f"Unexpected error in upload_media: {e}", exc_info=True)
            # Clean up any partial uploads
            if media:
                try:
                    media_service.delete_media(media)
                    logger.info(f"Cleaned up failed media {media.id}")
                except Exception as cleanup_error:
                    logger.error(
                        f"Failed to cleanup failed media {media.id}: {cleanup_error}"
                    )
            abort(500, message="Internal server error")

        finally:
            # Always clean up file streams
            if file_stream:
                try:
                    file_stream.close()
                except Exception as close_error:
                    logger.warning(f"Failed to close file stream: {close_error}")

            # Force garbage collection to free memory
            import gc

            gc.collect()


@bp.route("/<int:media_id>")
class MediaDetail(MethodView):
    @bp.response(200, MediaSchema)
    @bp.alt_response(404, description="Media not found")
    def get(self, media_id):
        """Get media by ID"""
        media = Media.query.get_or_404(media_id)

        # Check if media is soft-deleted
        if media.is_deleted:
            abort(404, message="Media not found")

        return media


@bp.route("/<int:media_id>/urls")
class MediaUrls(MethodView):
    @bp.response(200)
    def get(self, media_id):
        """Get all URLs for a media object"""
        media = Media.query.get_or_404(media_id)

        # Check if media is soft-deleted
        if media.is_deleted:
            abort(404, message="Media not found")

        include_variants = (
            request.args.get("include_variants", "true").lower() == "true"
        )
        return media_service.get_media_urls(media, include_variants=include_variants)


@bp.route("/<int:media_id>/status")
class MediaStatus(MethodView):
    @bp.response(200)
    def get(self, media_id):
        """Get media processing status and variants"""
        try:
            with session_scope() as session:
                media = session.query(Media).get(media_id)
                if not media or media.is_deleted:
                    abort(404, message="Media not found")

                # Get variants if processing is completed
                variants = []
                if media.processing_status == "completed":
                    variants = (
                        session.query(MediaVariant).filter_by(media_id=media_id).all()
                    )

                return {
                    "media_id": media_id,
                    "processing_status": media.processing_status,
                    "processing_error": media.processing_error
                    if hasattr(media, "processing_error")
                    else None,
                    "variants_count": len(variants),
                    "variants": [
                        {
                            "id": variant.id,
                            "variant_type": variant.variant_type.value,
                            "width": variant.width,
                            "height": variant.height,
                            "file_size": variant.file_size,
                            "quality": variant.quality,
                            "format": variant.format,
                        }
                        for variant in variants
                    ],
                    "urls": media_service.get_media_urls(media, include_variants=True),
                    "created_at": media.created_at,
                    "updated_at": media.updated_at
                    if hasattr(media, "updated_at") and media.updated_at
                    else None,
                }
        except Exception as e:
            logger.error(f"Error getting media status: {e}")
            abort(500, message="Failed to get media status")


@bp.route("/<int:media_id>/social-optimize")
class SocialMediaOptimization(MethodView):
    @bp.arguments(SocialMediaOptimizationSchema)
    @bp.response(200, SocialMediaOptimizationResponseSchema)
    @bp.alt_response(404, description="Media not found")
    def post(self, args, media_id):
        """Get optimized URLs for social media platforms"""
        media = Media.query.get_or_404(media_id)

        # Check if media is soft-deleted
        if media.is_deleted:
            abort(404, message="Media not found")

        result = media_service.optimize_for_social_media(
            media=media, platform=args["platform"], post_type=args["post_type"]
        )

        return {
            "platform": args["platform"],
            "post_type": args["post_type"],
            "optimized_url": result.get("optimized"),
            "original_url": result.get("original"),
            "dimensions": {},  # TODO: Add actual dimensions
            "file_size": 0,  # TODO: Add actual file size
        }


@bp.route("/<int:media_id>/remove-background")
class BackgroundRemoval(MethodView):
    @login_required
    @bp.response(200)
    @bp.alt_response(400, description="Background removal only supported for images")
    @bp.alt_response(404, description="Media not found")
    def post(self, media_id):
        """Remove background from image (placeholder)"""
        media = Media.query.get_or_404(media_id)

        # Check if media is soft-deleted
        if media.is_deleted:
            abort(404, message="Media not found")

        if media.media_type != MediaType.IMAGE:
            abort(400, message="Background removal only supported for images")

        # TODO: Implement background removal
        success = media_service.remove_background(media_id)

        return {
            "success": success,
            "message": "Background removal requested (not implemented yet)",
        }


@bp.route("/<int:media_id>")
class MediaDelete(MethodView):
    @login_required
    @bp.response(200, MediaDeleteSchema)
    @bp.alt_response(403, description="Not authorized to delete this media")
    @bp.alt_response(404, description="Media not found")
    def delete(self, media_id):
        """Soft delete media and all its variants"""
        media = Media.query.get_or_404(media_id)

        # Check ownership
        if media.user_id != current_user.id and not current_user.is_admin:
            abort(403, message="Not authorized to delete this media")

        # Check if already deleted
        if media.is_deleted:
            abort(400, message="Media is already deleted")

        try:
            # Soft delete media
            success = media_service.delete_media(media, hard_delete=False)

            if success:
                # Commit the soft delete
                with session_scope() as session:
                    session.merge(media)
                    session.commit()

                return {
                    "success": True,
                    "message": "Media deleted successfully",
                    "deleted_files": 1 + len(media.variants)
                    if hasattr(media, "variants")
                    else 1,
                }
            else:
                abort(500, message="Failed to delete media")

        except Exception as e:
            logger.error(f"Error deleting media {media_id}: {e}")
            abort(500, message="Failed to delete media")


@bp.route("/")
class MediaList(MethodView):
    @bp.arguments(MediaFilterSchema, location="query")
    @bp.response(200, MediaListSchema)
    def get(self, args):
        """List media with filtering and pagination"""
        query = Media.query.filter(
            Media.deleted_at.is_(None)
        )  # Exclude soft-deleted media

        # Apply filters
        if args.get("media_type"):
            query = query.filter(Media.media_type == args["media_type"])

        if args.get("user_id"):
            query = query.filter(Media.user_id == args["user_id"])

        if args.get("is_public") is not None:
            query = query.filter(Media.is_public == args["is_public"])

        if args.get("processing_status"):
            query = query.filter(Media.processing_status == args["processing_status"])

        if args.get("created_after"):
            query = query.filter(Media.created_at >= args["created_after"])

        if args.get("created_before"):
            query = query.filter(Media.created_at <= args["created_before"])

        # Order by creation date
        query = query.order_by(desc(Media.created_at))

        # Paginate using our custom Paginator
        page = args.get("page", 1)
        per_page = args.get("per_page", 20)

        paginator = Paginator(query, page=page, per_page=per_page)
        result = paginator.paginate(args)

        return {
            "media": result["items"],
            "total": result["total_items"],
            "page": result["page"],
            "per_page": result["per_page"],
            "has_next": result["page"] < result["total_pages"],
            "has_prev": result["page"] > 1,
        }


@bp.route("/stats")
class MediaStats(MethodView):
    @admin_required
    @bp.response(200, MediaStatsSchema)
    def get(self):
        """Get media statistics (admin only)"""
        try:
            # Get basic counts
            total_media = Media.query.count()
            total_images = Media.query.filter(
                Media.media_type == MediaType.IMAGE
            ).count()
            total_videos = Media.query.filter(
                Media.media_type == MediaType.VIDEO
            ).count()

            # Get size statistics
            with session_scope() as session:
                size_stats = session.query(
                    func.sum(Media.file_size).label("total_size"),
                    func.avg(Media.file_size).label("avg_size"),
                ).first()

            # Get variant count
            total_variants = MediaVariant.query.count()

            return {
                "total_media": total_media,
                "total_images": total_images,
                "total_videos": total_videos,
                "total_size": size_stats.total_size if size_stats else 0,
                "average_file_size": float(size_stats.avg_size if size_stats else 0),
                "variants_generated": total_variants,
                "processing_time_avg": 0.0,  # TODO: Track actual processing times
            }

        except Exception as e:
            logger.error(f"Error getting media stats: {e}")
            abort(500, message="Failed to get media statistics")


# Product Image Routes
@bp.route("/products/<product_id>/images")
class ProductImages(MethodView):
    @login_required
    @bp.response(201, ProductImageSchema)
    @bp.alt_response(400, description="Invalid file or validation error")
    @bp.alt_response(404, description="Product not found")
    def post(self, product_id):
        """Add image to product"""
        try:
            from flask import request
            from werkzeug.utils import secure_filename
            from io import BytesIO

            # Check if file is present
            if "file" not in request.files:
                abort(400, message="No file provided")

            file = request.files["file"]
            if file.filename == "":
                abort(400, message="No file selected")

            # Validate file
            filename = secure_filename(file.filename)
            if not filename:
                abort(400, message="Invalid filename")

            # Read file into memory
            file_stream = BytesIO(file.read())
            file_stream.seek(0)

            # Get form data
            sort_order = int(request.form.get("sort_order", 0))
            is_featured = request.form.get("is_featured", "false").lower() == "true"
            alt_text = request.form.get("alt_text")

            # Upload and link to product
            from app.products.services import ProductImageService

            product_image = ProductImageService.add_product_image(
                product_id=product_id,
                file_stream=file_stream,
                filename=filename,
                user_id=current_user.id,
                sort_order=sort_order,
                is_featured=is_featured,
                alt_text=alt_text,
            )

            return product_image

        except Exception as e:
            logger.error(f"Error adding product image: {e}")
            abort(500, message="Failed to add product image")

    @bp.response(200, ProductImageSchema(many=True))
    def get(self, product_id):
        """Get all images for a product"""
        from app.products.services import ProductImageService

        images = ProductImageService.get_product_images(product_id)
        return images


@bp.route("/products/<product_id>/images/<int:image_id>")
class ProductImageDetail(MethodView):
    @login_required
    @bp.response(200)
    @bp.alt_response(404, description="Product image not found")
    def delete(self, product_id, image_id):
        """Delete product image"""
        try:
            from app.products.services import ProductImageService
            from app.media.models import ProductImage

            # Get the product image to find the media
            product_image = ProductImage.query.get_or_404(image_id)

            # Verify it belongs to the specified product
            if product_image.product_id != product_id:
                abort(404, message="Product image not found")

            # Delete the product image (service handles media deletion)
            ProductImageService.delete_product_image(image_id, current_user.id)
            return {"success": True, "message": "Product image deleted"}

        except Exception as e:
            logger.error(f"Error deleting product image: {e}")
            abort(500, message="Failed to delete product image")


# Social Media Post Routes
@bp.route("/social-posts/<post_id>/media")
class SocialMediaPosts(MethodView):
    @login_required
    @bp.response(201, SocialMediaPostSchema)
    @bp.alt_response(400, description="Invalid file or validation error")
    @bp.alt_response(404, description="Post not found")
    def post(self, post_id):
        """Add media to social media post"""
        try:
            from flask import request
            from werkzeug.utils import secure_filename
            from io import BytesIO

            # Check if file is present
            if "file" not in request.files:
                abort(400, message="No file provided")

            file = request.files["file"]
            if file.filename == "":
                abort(400, message="No file selected")

            # Validate file
            filename = secure_filename(file.filename)
            if not filename:
                abort(400, message="Invalid filename")

            # Read file into memory
            file_stream = BytesIO(file.read())
            file_stream.seek(0)

            # Get form data
            platform = request.form.get("platform")
            post_type = request.form.get("post_type")
            aspect_ratio = request.form.get("aspect_ratio")

            # Upload and link to post
            from app.socials.services import PostService

            social_post = PostService.add_post_media(
                post_id=post_id,
                file_stream=file_stream,
                filename=filename,
                user_id=current_user.id,
                platform=platform or None,
                post_type=post_type or None,
                aspect_ratio=aspect_ratio,
            )

            return social_post

        except Exception as e:
            logger.error(f"Error adding social media post: {e}")
            abort(500, message="Failed to add social media post")

    @bp.response(200, SocialMediaPostSchema(many=True))
    def get(self, post_id):
        """Get all media for a social media post"""
        from app.socials.services import PostService

        posts = PostService.get_post_media(post_id)
        return posts


@bp.route("/social-posts/<post_id>/media/<int:media_id>")
class SocialMediaPostDetail(MethodView):
    @login_required
    @bp.response(200)
    @bp.alt_response(404, description="Social media post not found")
    def delete(self, post_id, media_id):
        """Delete social media post media"""
        try:
            from app.socials.services import PostService
            from app.media.models import SocialMediaPost

            # Get the social media post to find the media
            social_post = SocialMediaPost.query.get_or_404(media_id)

            # Verify it belongs to the specified post
            if social_post.post_id != post_id:
                abort(404, message="Social media post not found")

            # Delete the social media post (service handles media deletion)
            result = PostService.delete_post_media(media_id, current_user.id)
            return result

        except Exception as e:
            logger.error(f"Error deleting social media post: {e}")
            abort(500, message="Failed to delete social media post")


# Buyer Request Image Routes
@bp.route("/requests/<request_id>/images")
class RequestImages(MethodView):
    @login_required
    @bp.response(201, RequestImageSchema)
    @bp.alt_response(400, description="Invalid file or validation error")
    @bp.alt_response(404, description="Request not found")
    def post(self, request_id):
        """Add image to buyer request"""
        try:
            from flask import request
            from werkzeug.utils import secure_filename
            from io import BytesIO

            # Check if file is present
            if "file" not in request.files:
                abort(400, message="No file provided")

            file = request.files["file"]
            if file.filename == "":
                abort(400, message="No file selected")

            # Validate file
            filename = secure_filename(file.filename)
            if not filename:
                abort(400, message="Invalid filename")

            # Read file into memory
            file_stream = BytesIO(file.read())
            file_stream.seek(0)

            # Get form data
            is_primary = request.form.get("is_primary", "false").lower() == "true"

            # Upload and link to request
            from app.requests.services import BuyerRequestService

            request_image = BuyerRequestService.add_request_image(
                request_id=request_id,
                file_stream=file_stream,
                filename=filename,
                user_id=current_user.id,
                is_primary=is_primary,
            )

            return request_image

        except Exception as e:
            logger.error(f"Error adding request image: {e}")
            abort(500, message="Failed to add request image")

    @bp.response(200, RequestImageSchema(many=True))
    def get(self, request_id):
        """Get all images for a buyer request"""
        from app.requests.services import BuyerRequestService

        images = BuyerRequestService.get_request_images(request_id)
        return images


@bp.route("/requests/<request_id>/images/<int:image_id>")
class RequestImageDetail(MethodView):
    @login_required
    @bp.response(200)
    @bp.alt_response(404, description="Request image not found")
    def delete(self, request_id, image_id):
        """Delete request image"""
        try:
            from app.requests.services import BuyerRequestService
            from app.media.models import RequestImage

            # Get the request image to find the media
            request_image = RequestImage.query.get_or_404(image_id)

            # Verify it belongs to the specified request
            if request_image.request_id != request_id:
                abort(404, message="Request image not found")

            # Delete the request image (service handles media deletion)
            result = BuyerRequestService.delete_request_image(image_id, current_user.id)
            return result

        except Exception as e:
            logger.error(f"Error deleting request image: {e}")
            abort(500, message="Failed to delete request image")


# Utility Routes
@bp.route("/<int:media_id>/download")
class MediaDownload(MethodView):
    @bp.response(200)
    @bp.alt_response(403, description="Not authorized to access this media")
    @bp.alt_response(404, description="Media not found")
    def get(self, media_id):
        """Download media file (for authorized users)"""
        media = Media.query.get_or_404(media_id)

        # Check if user has access
        if not media.is_public and (
            not current_user.is_authenticated or media.user_id != current_user.id
        ):
            abort(403, message="Not authorized to access this media")

        # Generate presigned URL for download
        try:
            download_url = media_service.s3.generate_presigned_url(
                bucket_name=str(media_service.bucket),
                s3_key=media.storage_key,
                expiration=3600,  # 1 hour
                operation="get_object",
            )

            return {"download_url": download_url}

        except Exception as e:
            logger.error(f"Error generating download URL: {e}")
            abort(500, message="Failed to generate download URL")


@bp.route("/<int:media_id>/variants")
class MediaVariants(MethodView):
    @bp.response(200)
    @bp.alt_response(404, description="Media not found")
    def get(self, media_id):
        """Get all variants for a media object"""
        media = Media.query.get_or_404(media_id)

        variants = {}
        if hasattr(media, "variants") and media.variants:
            for variant in media.variants:
                variants[variant.variant_type.value] = {
                    "url": variant.get_url(),
                    "width": variant.width,
                    "height": variant.height,
                    "file_size": variant.file_size,
                }

        return variants


@bp.route("/<int:media_id>/generate-variants")
class GenerateVariants(MethodView):
    @login_required
    @bp.arguments(SocialMediaOptimizationSchema)
    @bp.response(200)
    @bp.alt_response(404, description="Media not found")
    @bp.alt_response(403, description="Not authorized to access this media")
    def post(self, args, media_id):
        """Generate on-demand variants for media"""
        try:
            # Get media object
            media = Media.query.get(media_id)
            if not media:
                abort(404, message="Media not found")

            # Check authorization
            if media.user_id != current_user.id and not current_user.is_admin:
                abort(403, message="Not authorized to access this media")

            # Determine which variants to generate based on request
            variant_types = []
            platform = args.get("platform")
            post_type = args.get("post_type")

            if platform == "instagram":
                if post_type == "story":
                    variant_types = [MediaVariantType.SOCIAL_STORY]
                else:
                    variant_types = [MediaVariantType.SOCIAL_SQUARE]
            elif platform == "facebook":
                variant_types = [MediaVariantType.SOCIAL_POST]
            elif platform == "twitter":
                variant_types = [MediaVariantType.SOCIAL_POST]
            elif platform == "linkedin":
                variant_types = [MediaVariantType.SOCIAL_POST]
            else:
                # Generate all on-demand variants
                variant_types = None

            # Generate variants
            variants = media_service.generate_on_demand_variants(
                media_id, variant_types
            )

            return {
                "success": True,
                "message": f"Generated {len(variants)} variants",
                "media_id": media_id,
                "variants_generated": len(variants),
            }

        except Exception as e:
            logger.error(f"Error generating variants for media {media_id}: {e}")
            abort(500, message="Failed to generate variants")
