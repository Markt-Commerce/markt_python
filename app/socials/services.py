import logging
import math
from datetime import datetime
import time
import re
from typing import Any, Dict, Optional

# package imports
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError

# project imports
from external.database import db
from external.redis import redis_client

from app.libs.session import session_scope
from app.libs.pagination import Paginator
from app.libs.errors import (
    NotFoundError,
    ValidationError,
    ConflictError,
    APIError,
    ForbiddenError,
)

from app.users.models import User, Seller, SellerVerificationStatus
from app.products.models import Product, ProductStatus
from app.products.services import ProductService, ProductStatsService
from app.orders.models import Order, OrderStatus, OrderItem
from app.notifications.models import NotificationType

# app imports
from .models import (
    Post,
    PostMedia,
    PostProduct,
    Follow,
    PostLike,
    PostComment,
    PostStatus,
    FollowType,
    ProductReview,
    ProductView,
    Niche,
    NicheMembership,
    NichePost,
    NicheModerationAction,
    NicheStatus,
    NicheVisibility,
    NicheMembershipRole,
)
from .constants import POST_STATUS_TRANSITIONS

logger = logging.getLogger(__name__)


class NicheService:
    """Service for managing niche communities with role-based access control"""

    # Cache keys
    CACHE_KEYS = {
        "niche": "niche:{niche_id}",
        "niche_members": "niche:{niche_id}:members",
        "niche_posts": "niche:{niche_id}:posts",
        "user_niches": "user:{user_id}:niches",
        "trending_niches": "trending:niches",
    }

    @staticmethod
    def create_niche(user_id: str, data: Dict[str, Any]) -> Niche:
        """Create a new niche community"""
        with session_scope() as session:
            # Validate user has seller account (sellers can create niches)
            user = session.query(User).get(user_id)
            if not user or not user.is_seller:
                raise ForbiddenError("Only sellers can create niche communities")

            # Validate niche data
            if not data.get("name") or not data.get("description"):
                raise ValidationError("Name and description are required")

            # Generate slug from name
            slug = NicheService._generate_slug(data["name"])

            # Check if slug already exists
            existing = session.query(Niche).filter_by(slug=slug).first()
            if existing:
                raise ConflictError("A community with this name already exists")

            # Create niche
            niche = Niche(
                name=data["name"],
                description=data["description"],
                slug=slug,
                visibility=NicheVisibility(data.get("visibility", "public")),
                allow_buyer_posts=data.get("allow_buyer_posts", True),
                allow_seller_posts=data.get("allow_seller_posts", True),
                require_approval=data.get("require_approval", False),
                max_members=data.get("max_members", 10000),
                category_id=data.get("category_id"),
                tags=data.get("tags", []),
                rules=data.get("rules", []),
                settings=data.get("settings", {}),
            )

            session.add(niche)
            session.flush()

            # Add creator as owner
            membership = NicheMembership(
                niche_id=niche.id,
                user_id=user_id,
                role=NicheMembershipRole.OWNER,
                is_active=True,
            )
            session.add(membership)

            # Update member count
            niche.member_count = 1

            # Cache invalidation
            NicheService._invalidate_user_cache(user_id)

            return niche

    @staticmethod
    def get_niche(niche_id: str, user_id: Optional[str] = None) -> Niche:
        """Get niche details with access control"""
        cache_key = NicheService.CACHE_KEYS["niche"].format(niche_id=niche_id)

        # Try cache first
        cached = redis_client.get(cache_key)
        if cached:
            return cached

        with session_scope() as session:
            niche = (
                session.query(Niche)
                .options(
                    joinedload(Niche.category),
                    joinedload(Niche.members).joinedload(NicheMembership.user),
                )
                .get(niche_id)
            )

            if not niche:
                raise NotFoundError("Community not found")

            # Check visibility and access
            if niche.visibility == NicheVisibility.PRIVATE:
                if not user_id:
                    raise ForbiddenError("This community is private")

                membership = (
                    session.query(NicheMembership)
                    .filter_by(niche_id=niche_id, user_id=user_id, is_active=True)
                    .first()
                )
                if not membership:
                    raise ForbiddenError("You don't have access to this community")

            # Cache for 10 minutes
            redis_client.setex(cache_key, 600, niche)

            return niche

    @staticmethod
    def join_niche(
        niche_id: str, user_id: str, invited_by: Optional[str] = None
    ) -> NicheMembership:
        """Join a niche community"""
        with session_scope() as session:
            niche = session.query(Niche).get(niche_id)
            if not niche:
                raise NotFoundError("Community not found")

            # Check if user is already a member
            existing_membership = (
                session.query(NicheMembership)
                .filter_by(niche_id=niche_id, user_id=user_id)
                .first()
            )

            if existing_membership:
                if existing_membership.is_active:
                    raise ConflictError("You are already a member of this community")
                else:
                    # Reactivate membership
                    existing_membership.is_active = True
                    existing_membership.is_banned = False
                    existing_membership.banned_until = None
                    existing_membership.ban_reason = None
                    existing_membership.joined_at = datetime.utcnow()
                    membership = existing_membership
            else:
                # Check member limit
                if niche.member_count >= niche.max_members:
                    raise ValidationError("This community has reached its member limit")

                # Create new membership
                membership = NicheMembership(
                    niche_id=niche_id,
                    user_id=user_id,
                    role=NicheMembershipRole.MEMBER,
                    invited_by=invited_by,
                    is_active=True,
                )
                session.add(membership)

                # Update member count
                niche.member_count += 1

            # Cache invalidation
            NicheService._invalidate_niche_cache(niche_id)
            NicheService._invalidate_user_cache(user_id)

            return membership

    @staticmethod
    def leave_niche(niche_id: str, user_id: str) -> bool:
        """Leave a niche community"""
        with session_scope() as session:
            membership = (
                session.query(NicheMembership)
                .filter_by(niche_id=niche_id, user_id=user_id, is_active=True)
                .first()
            )

            if not membership:
                raise NotFoundError("You are not a member of this community")

            # Owners cannot leave (must transfer ownership first)
            if membership.role == NicheMembershipRole.OWNER:
                raise ValidationError("Owners cannot leave. Transfer ownership first.")

            # Deactivate membership
            membership.is_active = False

            # Update member count
            niche = session.query(Niche).get(niche_id)
            if niche and niche.member_count > 0:
                niche.member_count -= 1

            # Cache invalidation
            NicheService._invalidate_niche_cache(niche_id)
            NicheService._invalidate_user_cache(user_id)

            return True

    @staticmethod
    def get_niche_members(niche_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get paginated list of niche members with role filtering"""
        with session_scope() as session:
            base_query = (
                session.query(NicheMembership)
                .filter_by(niche_id=niche_id, is_active=True)
                .options(
                    joinedload(NicheMembership.user),
                    joinedload(NicheMembership.inviter),
                )
                .order_by(NicheMembership.role.desc(), NicheMembership.joined_at.asc())
            )

            # Apply role filter
            if args.get("role"):
                base_query = base_query.filter(NicheMembership.role == args["role"])

            paginator = Paginator(
                base_query, page=args.get("page", 1), per_page=args.get("per_page", 20)
            )
            return paginator.paginate(args)

    @staticmethod
    def get_user_niches(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get user's niche memberships"""
        cache_key = NicheService.CACHE_KEYS["user_niches"].format(user_id=user_id)

        # Try cache for first page
        if args.get("page", 1) == 1:
            cached = redis_client.get(cache_key)
            if cached:
                return cached

        with session_scope() as session:
            base_query = (
                session.query(NicheMembership)
                .filter_by(user_id=user_id, is_active=True)
                .options(
                    joinedload(NicheMembership.niche).joinedload(Niche.category),
                )
                .order_by(NicheMembership.last_activity.desc())
            )

            paginator = Paginator(
                base_query, page=args.get("page", 1), per_page=args.get("per_page", 20)
            )
            result = paginator.paginate(args)

            # Cache first page for 5 minutes
            if args.get("page", 1) == 1:
                redis_client.setex(cache_key, 300, result)

            return result

    @staticmethod
    def search_niches(
        args: Dict[str, Any], user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search niches with visibility filtering"""
        with session_scope() as session:
            base_query = session.query(Niche).filter(Niche.status == NicheStatus.ACTIVE)

            # Apply visibility filter
            if user_id:
                # Logged in users can see public and restricted niches
                base_query = base_query.filter(
                    Niche.visibility.in_(
                        [NicheVisibility.PUBLIC, NicheVisibility.RESTRICTED]
                    )
                )
            else:
                # Anonymous users can only see public niches
                base_query = base_query.filter(
                    Niche.visibility == NicheVisibility.PUBLIC
                )

            # Apply search filters
            if args.get("search"):
                search_term = f"%{args['search']}%"
                base_query = base_query.filter(
                    db.or_(
                        Niche.name.ilike(search_term),
                        Niche.description.ilike(search_term),
                    )
                )

            if args.get("category_id"):
                base_query = base_query.filter(Niche.category_id == args["category_id"])

            # Order by relevance (member count, activity)
            base_query = base_query.order_by(
                Niche.member_count.desc(),
                Niche.post_count.desc(),
                Niche.created_at.desc(),
            )

            paginator = Paginator(
                base_query, page=args.get("page", 1), per_page=args.get("per_page", 20)
            )
            return paginator.paginate(args)

    @staticmethod
    def moderate_user(
        niche_id: str,
        moderator_id: str,
        target_user_id: str,
        action_data: Dict[str, Any],
    ) -> NicheModerationAction:
        """Perform moderation action on a user"""
        with session_scope() as session:
            # Validate moderator permissions
            moderator_membership = (
                session.query(NicheMembership)
                .filter_by(niche_id=niche_id, user_id=moderator_id, is_active=True)
                .first()
            )

            if not moderator_membership or moderator_membership.role not in [
                NicheMembershipRole.MODERATOR,
                NicheMembershipRole.ADMIN,
                NicheMembershipRole.OWNER,
            ]:
                raise ForbiddenError("You don't have moderation permissions")

            # Validate target user membership
            target_membership = (
                session.query(NicheMembership)
                .filter_by(niche_id=niche_id, user_id=target_user_id, is_active=True)
                .first()
            )

            if not target_membership:
                raise NotFoundError("Target user is not a member of this community")

            # Prevent moderating users with higher roles
            if target_membership.role.value >= moderator_membership.role.value:
                raise ForbiddenError(
                    "You cannot moderate users with equal or higher roles"
                )

            # Create moderation action
            action = NicheModerationAction(
                niche_id=niche_id,
                moderator_id=moderator_id,
                target_user_id=target_user_id,
                action_type=action_data["action_type"],
                reason=action_data["reason"],
                duration=action_data.get("duration"),
                target_type=action_data.get("target_type", "user"),
                target_id=action_data.get("target_id"),
                is_active=True,
            )

            # Apply action
            if action_data["action_type"] == "ban":
                target_membership.is_banned = True
                target_membership.banned_until = action_data.get("banned_until")
                target_membership.ban_reason = action_data["reason"]

                if action_data.get("banned_until"):
                    action.expires_at = action_data["banned_until"]

            elif action_data["action_type"] == "warn":
                # Warning is just logged
                pass

            session.add(action)

            # Cache invalidation
            NicheService._invalidate_niche_cache(niche_id)
            NicheService._invalidate_user_cache(target_user_id)

            return action

    @staticmethod
    def can_user_post_in_niche(niche_id: str, user_id: str) -> Dict[str, Any]:
        """Check if user can post in niche with role-based rules"""
        with session_scope() as session:
            niche = session.query(Niche).get(niche_id)
            if not niche:
                return {"can_post": False, "reason": "Community not found"}

            user = session.query(User).get(user_id)
            if not user:
                return {"can_post": False, "reason": "User not found"}

            # Check membership
            membership = (
                session.query(NicheMembership)
                .filter_by(niche_id=niche_id, user_id=user_id, is_active=True)
                .first()
            )

            if not membership:
                return {"can_post": False, "reason": "You must be a member to post"}

            # Check if banned
            if membership.is_banned:
                if (
                    membership.banned_until
                    and membership.banned_until > datetime.utcnow()
                ):
                    return {
                        "can_post": False,
                        "reason": f"You are banned until {membership.banned_until}",
                    }
                elif not membership.banned_until:
                    return {"can_post": False, "reason": "You are permanently banned"}

            # Check role-based posting rules
            if user.is_buyer and not niche.allow_buyer_posts:
                return {
                    "can_post": False,
                    "reason": "Buyers cannot post in this community",
                }

            if user.is_seller and not niche.allow_seller_posts:
                return {
                    "can_post": False,
                    "reason": "Sellers cannot post in this community",
                }

            return {"can_post": True, "requires_approval": niche.require_approval}

    # Private helper methods
    @staticmethod
    def _generate_slug(name: str) -> str:
        """Generate URL-friendly slug from name"""
        # Convert to lowercase and replace spaces with hyphens
        slug = re.sub(r"[^\w\s-]", "", name.lower())
        slug = re.sub(r"[-\s]+", "-", slug)
        return slug.strip("-")

    @staticmethod
    def _invalidate_niche_cache(niche_id: str):
        """Invalidate niche-related caches"""
        redis_client.delete(NicheService.CACHE_KEYS["niche"].format(niche_id=niche_id))
        redis_client.delete(
            NicheService.CACHE_KEYS["niche_members"].format(niche_id=niche_id)
        )
        redis_client.delete(
            NicheService.CACHE_KEYS["niche_posts"].format(niche_id=niche_id)
        )

    @staticmethod
    def _invalidate_user_cache(user_id: str):
        """Invalidate user-related caches"""
        redis_client.delete(
            NicheService.CACHE_KEYS["user_niches"].format(user_id=user_id)
        )


class PostService:
    @staticmethod
    def create_post(seller_id, post_data):
        try:
            with session_scope() as session:
                # Verify seller exists
                seller = session.query(Seller).get(seller_id)
                if not seller:
                    raise NotFoundError("Seller not found")

                # Set status from request or default to draft
                status = PostStatus(post_data.get("status", "draft"))

                post = Post(
                    seller_id=seller_id, caption=post_data.get("caption"), status=status
                )
                session.add(post)
                session.flush()

                # Add media if provided
                if "media" in post_data:
                    for media_data in post_data["media"]:
                        media = PostMedia(
                            post_id=post.id,
                            media_url=media_data["media_url"],
                            media_type=media_data["media_type"],
                            sort_order=media_data.get("sort_order", 0),
                        )
                        session.add(media)

                # Add tagged products if provided
                if "products" in post_data:
                    for product_data in post_data["products"]:
                        # Verify product belongs to seller
                        product = session.query(Product).get(product_data["product_id"])
                        if not product or product.seller_id != seller_id:
                            raise ValidationError("Invalid product ID")

                        post_product = PostProduct(
                            post_id=post.id, product_id=product_data["product_id"]
                        )
                        session.add(post_product)

                # Update Redis counters - now using seller_id
                redis_client.zadd(
                    f"seller:{seller_id}:posts",
                    {post.id: int(post.created_at.timestamp())},
                )

                return post
        except SQLAlchemyError as e:
            logger.error(f"Error creating post: {str(e)}")
            raise ConflictError("Failed to create post")
        except (RedisError, RedisConnectionError) as e:
            logger.warning(f"Redis error while creating post: {str(e)}")

    @staticmethod
    def get_post(post_id):
        try:
            with session_scope() as session:
                post = (
                    session.query(Post)
                    .options(
                        joinedload(Post.seller).joinedload(Seller.user),
                        joinedload(Post.media),
                        joinedload(Post.tagged_products).joinedload(
                            PostProduct.product
                        ),
                    )
                    .get(post_id)
                )
                if not post:
                    raise NotFoundError("Post not found")
                return post
        except SQLAlchemyError as e:
            logger.error(f"Error fetching post {post_id}: {str(e)}")
            raise NotFoundError("Failed to fetch post")

    @staticmethod
    def get_seller_posts(seller_id, page=1, per_page=20):
        """Get paginated posts by seller"""
        with session_scope() as session:
            base_query = (
                session.query(Post)
                .filter(Post.seller_id == seller_id, Post.status == PostStatus.ACTIVE)
                .options(
                    joinedload(Post.media),
                    joinedload(Post.tagged_products).joinedload(PostProduct.product),
                    # Add these to load the relationships needed for counting
                    joinedload(Post.likes),
                    joinedload(Post.comments),
                )
            )
            paginator = Paginator(base_query, page=page, per_page=per_page)
            result = paginator.paginate({})  # Pass empty dict if no filters

            return {
                "items": result["items"],
                "pagination": {
                    "page": result["page"],
                    "per_page": result["per_page"],
                    "total_items": result["total_items"],
                    "total_pages": result["total_pages"],
                },
            }

    @staticmethod
    def like_post(user_id, post_id):
        try:
            with session_scope() as session:
                # Check if like already exists
                existing_like = (
                    session.query(PostLike)
                    .filter_by(user_id=user_id, post_id=post_id)
                    .first()
                )

                if existing_like:
                    raise ConflictError("Post already liked")

                like = PostLike(user_id=user_id, post_id=post_id)
                session.add(like)

                # Update Redis counters
                redis_client.zincrby(f"post:{post_id}:likes", 1, user_id)
                redis_client.zincrby(f"user:{user_id}:liked_posts", 1, post_id)

                # Get post owner
                post = session.query(Post).get(post_id)
                if post.seller.user_id != user_id:  # Don't notify for self-likes
                    from app.notifications.services import NotificationService

                    NotificationService.create_notification(
                        user_id=post.seller.user_id,
                        notification_type=NotificationType.POST_LIKE,
                        actor_id=user_id,
                        reference_type="post",
                        reference_id=post_id,
                    )

                return like
        except SQLAlchemyError as e:
            logger.error(f"Error liking post: {str(e)}")
            raise ConflictError("Failed to like post")
        except (RedisError, RedisConnectionError) as e:
            logger.warning(f"Redis error while liking post: {str(e)}")

    @staticmethod
    def unlike_post(user_id, post_id):
        try:
            with session_scope() as session:
                like = (
                    session.query(PostLike)
                    .filter_by(user_id=user_id, post_id=post_id)
                    .first()
                )
                if like:
                    session.delete(like)
                    redis_client.zincrby(f"post:{post_id}:likes", -1, user_id)
                    redis_client.zincrby(f"user:{user_id}:liked_posts", -1, post_id)
        except SQLAlchemyError as e:
            logger.error(f"Error unliking post: {str(e)}")
            raise ConflictError("Failed to unlike post")
        except (RedisError, RedisConnectionError) as e:
            logger.warning(f"Redis error while unliking post: {str(e)}")

    @staticmethod
    def update_post(post_id, seller_id, update_data):
        """Update post details (caption, media, products)"""
        try:
            with session_scope() as session:
                post = session.query(Post).get(post_id)
                if not post:
                    raise NotFoundError("Post not found")
                if post.seller_id != seller_id:
                    raise ValidationError("You can only edit your own posts")
                if post.status == PostStatus.DELETED:
                    raise ValidationError("Cannot edit deleted posts")

                # Update caption if provided
                if "caption" in update_data:
                    post.caption = update_data["caption"]

                # Handle media updates
                if "media" in update_data:
                    # Clear existing media
                    session.query(PostMedia).filter_by(post_id=post_id).delete()

                    # Add new media
                    for media_data in update_data["media"]:
                        media = PostMedia(
                            post_id=post.id,
                            media_url=media_data["media_url"],
                            media_type=media_data["media_type"],
                            sort_order=media_data.get("sort_order", 0),
                        )
                        session.add(media)

                # Handle product updates
                if "products" in update_data:
                    # Clear existing products
                    session.query(PostProduct).filter_by(post_id=post_id).delete()

                    # Add new products
                    for product_data in update_data["products"]:
                        product = session.query(Product).get(product_data["product_id"])
                        if not product or product.seller_id != seller_id:
                            raise ValidationError("Invalid product ID")

                        post_product = PostProduct(
                            post_id=post.id, product_id=product_data["product_id"]
                        )
                        session.add(post_product)

                return post
        except SQLAlchemyError as e:
            logger.error(f"Error updating post {post_id}: {str(e)}")
            raise ConflictError("Failed to update post")

    @staticmethod
    def change_post_status(post_id, seller_id, new_status):
        """Change post status (publish, archive, etc)"""
        try:
            with session_scope() as session:
                post = session.query(Post).get(post_id)
                if not post:
                    raise NotFoundError("Post not found")
                if post.seller_id != seller_id:
                    raise ValidationError("You can only modify your own posts")

                status_mapping = POST_STATUS_TRANSITIONS

                if new_status not in status_mapping:
                    raise ValidationError("Invalid status transition")

                current_status, target_status = status_mapping[new_status]

                if current_status is not None and post.status != current_status:
                    raise ValidationError(
                        f"Cannot {new_status} a {post.status.value} post"
                    )

                post.status = target_status

                # Handle Redis updates for status changes
                if new_status == "publish":
                    # Add to seller's active posts in Redis
                    redis_client.zadd(
                        f"seller:{seller_id}:posts",
                        {post.id: int(post.created_at.timestamp())},
                    )
                elif new_status == "delete":
                    # Remove from seller's posts in Redis
                    redis_client.zrem(f"seller:{seller_id}:posts", post.id)

                return post
        except SQLAlchemyError as e:
            logger.error(f"Error changing post status {post_id}: {str(e)}")
            raise ConflictError("Failed to change post status")
        except (RedisError, RedisConnectionError) as e:
            logger.warning(f"Redis error while changing post status: {str(e)}")

    @staticmethod
    def get_seller_drafts(seller_id, page=1, per_page=20):
        """Get seller's draft posts"""
        with session_scope() as session:
            base_query = (
                session.query(Post)
                .filter(Post.seller_id == seller_id, Post.status == PostStatus.DRAFT)
                .options(
                    joinedload(Post.media),
                    joinedload(Post.tagged_products).joinedload(PostProduct.product),
                )
            )
            paginator = Paginator(base_query, page=page, per_page=per_page)
            return paginator.paginate({})

    @staticmethod
    def get_seller_archived(seller_id, page=1, per_page=20):
        """Get seller's archived posts"""
        with session_scope() as session:
            base_query = (
                session.query(Post)
                .filter(Post.seller_id == seller_id, Post.status == PostStatus.ARCHIVED)
                .options(
                    joinedload(Post.media),
                    joinedload(Post.tagged_products).joinedload(PostProduct.product),
                )
            )
            paginator = Paginator(base_query, page=page, per_page=per_page)
            return paginator.paginate({})

    @staticmethod
    def add_comment(user_id, post_id, content, parent_id=None):
        """Add a comment to a post"""
        try:
            with session_scope() as session:
                post = session.query(Post).get(post_id)
                if not post or post.status != PostStatus.ACTIVE:
                    raise NotFoundError("Post not found or not active")

                comment = PostComment(
                    user_id=user_id,
                    post_id=post_id,
                    content=content,
                    parent_id=parent_id,
                )
                session.add(comment)

                # Update Redis counters
                redis_client.zincrby(f"post:{post_id}:comments", 1, user_id)

                # Notify post owner if not self-comment
                if post.seller.user_id != user_id:
                    from app.notifications.services import NotificationService

                    NotificationService.create_notification(
                        user_id=post.seller.user_id,
                        notification_type=NotificationType.POST_COMMENT,
                        actor_id=user_id,
                        reference_type="post",
                        reference_id=post_id,
                    )

                return comment
        except SQLAlchemyError as e:
            logger.error(f"Error adding comment: {str(e)}")
            raise ConflictError("Failed to add comment")
        except (RedisError, RedisConnectionError) as e:
            logger.warning(f"Redis error while adding comment: {str(e)}")

    @staticmethod
    def update_comment(comment_id, user_id, content):
        """Update a comment"""
        try:
            with session_scope() as session:
                comment = session.query(PostComment).get(comment_id)
                if not comment:
                    raise NotFoundError("Comment not found")
                if comment.user_id != user_id:
                    raise ValidationError("You can only edit your own comments")

                comment.content = content
                return comment
        except SQLAlchemyError as e:
            logger.error(f"Error updating comment: {str(e)}")
            raise ConflictError("Failed to update comment")

    @staticmethod
    def delete_comment(comment_id, user_id):
        """Delete a comment"""
        try:
            with session_scope() as session:
                comment = session.query(PostComment).get(comment_id)
                if not comment:
                    raise NotFoundError("Comment not found")

                # Allow post owner or comment author to delete
                post_owner_id = comment.post.seller.user_id
                if comment.user_id != user_id and post_owner_id != user_id:
                    raise ValidationError("Not authorized to delete this comment")

                session.delete(comment)

                # Update Redis counters
                redis_client.zincrby(
                    f"post:{comment.post_id}:comments", -1, comment.user_id
                )
        except SQLAlchemyError as e:
            logger.error(f"Error deleting comment: {str(e)}")
            raise ConflictError("Failed to delete comment")

    @staticmethod
    def get_post_comments(post_id, page=1, per_page=20):
        """Get comments for a post"""
        with session_scope() as session:
            base_query = (
                session.query(PostComment)
                .filter_by(post_id=post_id, parent_id=None)  # Only top-level comments
                .options(
                    joinedload(PostComment.user),
                    joinedload(PostComment.replies).joinedload(PostComment.user),
                )
                .order_by(PostComment.created_at.desc())
            )
            paginator = Paginator(base_query, page=page, per_page=per_page)
            return paginator.paginate({})

    @staticmethod
    def get_posts(args):
        """Get paginated posts with filtering"""
        with session_scope() as session:
            base_query = (
                session.query(Post)
                .filter(Post.status == PostStatus.ACTIVE)
                .options(
                    joinedload(Post.seller).joinedload(Seller.user),
                    joinedload(Post.media),
                    joinedload(Post.tagged_products).joinedload(PostProduct.product),
                    joinedload(Post.likes),
                    joinedload(Post.comments),
                )
            )

            # Apply filters
            if args.get("seller_id"):
                base_query = base_query.filter(Post.seller_id == args["seller_id"])

            if args.get("category_id"):
                base_query = base_query.join(Seller).filter(
                    Seller.category_id == args["category_id"]
                )

            # Order by creation date
            base_query = base_query.order_by(Post.created_at.desc())

            paginator = Paginator(
                base_query, page=args.get("page", 1), per_page=args.get("per_page", 20)
            )
            result = paginator.paginate(args)

            return {
                "items": result["items"],
                "pagination": {
                    "page": result["page"],
                    "per_page": result["per_page"],
                    "total_items": result["total_items"],
                    "total_pages": result["total_pages"],
                },
            }

    @staticmethod
    def delete_post(post_id, seller_id):
        """Delete post (seller only)"""
        with session_scope() as session:
            post = session.query(Post).get(post_id)
            if not post:
                raise NotFoundError("Post not found")

            if post.seller_id != seller_id:
                raise ForbiddenError("You can only delete your own posts")

            # Soft delete by changing status
            post.status = PostStatus.DELETED
            post.updated_at = datetime.utcnow()

            # Remove from Redis
            redis_client.zrem(f"seller:{seller_id}:posts", post_id)

            return True

    @staticmethod
    def update_post_status(post_id, seller_id, new_status):
        """Update post status (seller only)"""
        with session_scope() as session:
            post = session.query(Post).get(post_id)
            if not post:
                raise NotFoundError("Post not found")

            if post.seller_id != seller_id:
                raise ForbiddenError("You can only update your own posts")

            # Validate status transition
            valid_transitions = {
                PostStatus.DRAFT: [PostStatus.ACTIVE, PostStatus.ARCHIVED],
                PostStatus.ACTIVE: [PostStatus.ARCHIVED, PostStatus.DELETED],
                PostStatus.ARCHIVED: [PostStatus.ACTIVE, PostStatus.DELETED],
            }

            if new_status not in valid_transitions.get(post.status, []):
                raise ValidationError(
                    f"Invalid status transition from {post.status} to {new_status}"
                )

            post.status = PostStatus(new_status)
            post.updated_at = datetime.utcnow()

            return post

    @staticmethod
    def toggle_like(user_id, post_id):
        """Toggle like on post"""
        with session_scope() as session:
            # Check if like already exists
            existing_like = (
                session.query(PostLike)
                .filter_by(user_id=user_id, post_id=post_id)
                .first()
            )

            if existing_like:
                # Unlike
                session.delete(existing_like)
                redis_client.zincrby(f"post:{post_id}:likes", -1, user_id)
                redis_client.zrem(f"user:{user_id}:liked_posts", post_id)
                return {"liked": False, "message": "Post unliked"}
            else:
                # Like
                like = PostLike(user_id=user_id, post_id=post_id)
                session.add(like)
                redis_client.zincrby(f"post:{post_id}:likes", 1, user_id)
                redis_client.zadd(
                    f"user:{user_id}:liked_posts",
                    {post_id: int(datetime.utcnow().timestamp())},
                )

                # Notify post owner
                post = session.query(Post).get(post_id)
                if post.seller.user_id != user_id:
                    from app.notifications.services import NotificationService

                    NotificationService.create_notification(
                        user_id=post.seller.user_id,
                        notification_type=NotificationType.POST_LIKE,
                        reference_type="post",
                        reference_id=post_id,
                        metadata_={"actor_id": user_id},
                    )

                return {"liked": True, "message": "Post liked"}

    @staticmethod
    def get_comment(comment_id):
        """Get comment by ID"""
        with session_scope() as session:
            comment = (
                session.query(PostComment)
                .options(joinedload(PostComment.user))
                .get(comment_id)
            )
            if not comment:
                raise NotFoundError("Comment not found")
            return comment

    @staticmethod
    def create_comment(user_id, post_id, comment_data):
        """Create comment on post"""
        with session_scope() as session:
            # Verify post exists and is active
            post = session.query(Post).get(post_id)
            if not post:
                raise NotFoundError("Post not found")
            if post.status != PostStatus.ACTIVE:
                raise ValidationError("Cannot comment on inactive post")

            comment = PostComment(
                user_id=user_id,
                post_id=post_id,
                content=comment_data["content"],
                parent_id=comment_data.get("parent_id"),
            )
            session.add(comment)
            session.flush()

            # Notify post owner
            if post.seller.user_id != user_id:
                from app.notifications.services import NotificationService

                NotificationService.create_notification(
                    user_id=post.seller.user_id,
                    notification_type=NotificationType.POST_COMMENT,
                    reference_type="post",
                    reference_id=post_id,
                    metadata_={"comment_id": comment.id, "actor_id": user_id},
                )

            return comment


class ProductSocialService:
    @staticmethod
    def create_review(user_id, product_id, data):
        try:
            with session_scope() as session:
                product = session.query(Product).get(product_id)
                if not product:
                    raise NotFoundError("Product not found")

                # Verify purchase if order_id provided
                if data.get("order_id"):
                    order = (
                        session.query(Order)
                        .filter_by(
                            id=data["order_id"],
                            buyer_id=user_id,
                            status=OrderStatus.DELIVERED,
                        )
                        .join(OrderItem)
                        .filter_by(product_id=product_id)
                        .first()
                    )

                    if not order:
                        raise APIError(
                            "You must purchase this product before reviewing", 403
                        )

                    data["is_verified"] = True

                # Check for existing review
                existing = (
                    session.query(ProductReview)
                    .filter_by(user_id=user_id, product_id=product_id)
                    .first()
                )

                if existing:
                    raise APIError("You've already reviewed this product", 400)

                # Create rating
                review = ProductReview(user_id=user_id, product_id=product_id, **data)
                session.add(review)
                session.flush()

                # Update Redis
                redis_key = f"product:{product_id}:stats"

                with redis_client.pipeline() as pipe:
                    if data.get("rating"):
                        pipe.hincrby(redis_key, "rating_sum", data["rating"])
                        pipe.hincrby(redis_key, "rating_count", 1)

                    pipe.hincrby(redis_key, "review_count", 1)
                    pipe.execute()

                # Update all derived stats
                ProductStatsService.update_product_stats(product_id)

                # Trigger notification
                from app.notifications.services import NotificationService

                NotificationService.create_notification(
                    user_id=product.seller.user_id,
                    notification_type=NotificationType.PRODUCT_REVIEW,
                    actor_id=user_id,
                    reference_type="product",
                    reference_id=product_id,
                    metadata_={
                        "product_name": product.name,
                        "rating": data.get("rating", 0),
                    },
                )

                # Trigger socket event
                # from main.extensions import socketio
                # socketio.emit('review_added', {
                #     'product_id': product_id,
                #     'review_count': int(redis_client.hget(redis_key, "review_count")),
                #     'avg_rating': float(redis_client.hget(redis_key, "avg_rating") or 0),
                #     'user_id': user_id,
                #     'rating': data.get('rating')
                # }, room=f"product_{product_id}")

                return review
        except Exception as e:
            logger.error(f"Error adding review: {str(e)}")
            raise APIError("Failed to add review", 500)
        except SQLAlchemyError as e:
            logger.error(f"Error adding review: {str(e)}")
            raise ConflictError("Failed to add review")
        except (RedisError, RedisConnectionError) as e:
            logger.warning(f"Redis error while adding review: {str(e)}")

    @staticmethod
    def upvote_review(user_id, review_id):
        try:
            with session_scope() as session:
                review = session.query(ProductReview).get(review_id)
                if not review:
                    raise NotFoundError("Review not found")

                # Prevent self-upvoting
                if review.user_id == user_id:
                    raise APIError("Cannot upvote your own review", 400)

                review.upvotes += 1

                # Update Redis
                redis_client.zincrby(
                    f"product:{review.product_id}:helpful_reviews", 1, review_id
                )
                redis_client.zincrby(f"user:{user_id}:upvoted_reviews", 1, review_id)

                # Notify review author if different from upvoter
                if review.user_id != user_id:
                    from app.notifications.services import NotificationService

                    NotificationService.create_notification(
                        user_id=review.user_id,
                        notification_type=NotificationType.REVIEW_UPVOTE,
                        actor_id=user_id,
                        reference_type="review",
                        reference_id=review_id,
                        metadata_={},  # No metadata needed for upvote template
                    )

                # Trigger socket event
                # from main.extensions import socketio
                # socketio.emit('review_upvoted', {
                #     'review_id': review_id,
                #     'user_id': user_id,
                #     'upvotes': review.upvotes,
                #     'product_id': review.product_id
                # }, room=f"product_{review.product_id}")

                return review
        except SQLAlchemyError as e:
            logger.error(f"Error upvoting review: {str(e)}")
            raise ConflictError("Failed to upvote review")
        except (RedisError, RedisConnectionError) as e:
            logger.warning(f"Redis error while upvoting review: {str(e)}")

    @staticmethod
    def get_product_reviews(product_id, page=1, per_page=10):
        with session_scope() as session:
            base_query = (
                session.query(ProductReview)
                .filter_by(product_id=product_id)
                .options(joinedload(ProductReview.user))
                .order_by(ProductReview.upvotes.desc(), ProductReview.created_at.desc())
            )

            paginator = Paginator(base_query, page=page, per_page=per_page)
            return paginator.paginate({})

    @staticmethod
    def track_product_view(product_id, user_id=None, ip_address=None):
        """Record a product view"""
        try:
            with session_scope() as session:
                view = ProductView(
                    product_id=product_id, user_id=user_id, ip_address=ip_address
                )
                session.add(view)

                # Update Redis
                redis_key = f"product:{product_id}:stats"

                with redis_client.pipeline() as pipe:
                    if user_id:
                        pipe.zincrby(f"user:{user_id}:viewed_products", 1, product_id)

                    pipe.zincrby("trending_products", 1, product_id)
                    pipe.hincrby(redis_key, "view_count", 1)
                    pipe.hset(redis_key, "last_viewed", time.time())
                    pipe.execute()

                return view
        except SQLAlchemyError as e:
            logger.error(f"Error tracking product view: {str(e)}")


class FollowService:
    @staticmethod
    def follow_user(follower_id, followee_id):
        try:
            with session_scope() as session:
                # Check if follow relationship already exists
                existing_follow = (
                    session.query(Follow)
                    .filter_by(follower_id=follower_id, followee_id=followee_id)
                    .first()
                )

                if existing_follow:
                    raise ConflictError("Already following this user")

                # Get user types (implementation depends on your user model)
                follower = (
                    session.query(User)
                    .options(
                        joinedload(User.buyer_account), joinedload(User.seller_account)
                    )
                    .get(follower_id)
                )

                followee = (
                    session.query(User)
                    .options(joinedload(User.seller_account))
                    .get(followee_id)
                )

                # Validate followee can be followed (must be a seller)
                if not followee or not followee.seller_account:
                    raise ValidationError("You can only follow sellers")

                # Determine follow type based on permanent capabilities
                if follower.buyer_account and followee.seller_account:
                    follow_type = FollowType.CUSTOMER
                elif follower.seller_account and followee.seller_account:
                    follow_type = FollowType.PEER
                else:
                    raise ValidationError("Invalid follow relationship")

                follow = Follow(
                    follower_id=follower_id,
                    followee_id=followee_id,
                    follow_type=follow_type,
                )
                session.add(follow)

                # Update Redis counters
                redis_client.hincrby(f"user:{followee_id}", "followers_count", 1)
                redis_client.hincrby(f"user:{follower_id}", "following_count", 1)

                from app.notifications.services import NotificationService

                NotificationService.create_notification(
                    user_id=followee_id,
                    notification_type=NotificationType.NEW_FOLLOWER,
                    actor_id=follower_id,
                    reference_type="user",
                    reference_id=follower_id,
                )

                return follow
        except SQLAlchemyError as e:
            logger.error(f"Error following user: {str(e)}")
            raise ConflictError("Failed to follow user")

    @staticmethod
    def unfollow_user(follower_id, followee_id):
        """Unfollow a user"""
        try:
            with session_scope() as session:
                follow = (
                    session.query(Follow)
                    .filter_by(follower_id=follower_id, followee_id=followee_id)
                    .first()
                )
                if not follow:
                    raise NotFoundError("Follow relationship not found")

                session.delete(follow)

                # Update Redis counters
                redis_client.zrem(f"user:{follower_id}:following", followee_id)
                redis_client.zrem(f"user:{followee_id}:followers", follower_id)

                return True
        except SQLAlchemyError as e:
            logger.error(f"Error unfollowing user: {str(e)}")
            raise ConflictError("Failed to unfollow user")
        except (RedisError, RedisConnectionError) as e:
            logger.warning(f"Redis error while unfollowing user: {str(e)}")


class FeedService:
    @staticmethod
    def get_hybrid_feed(user_id, page=1, per_page=20):
        """Primary endpoint for feed consumption"""
        try:
            # Try Redis cache first
            cached_items = FeedService._get_cached_feed(user_id)

            if cached_items:
                feed_items = FeedService._hydrate_cached_items(cached_items)
            else:
                # Fallback to database generation
                feed_items = FeedService._generate_fresh_feed(user_id)

            return FeedService._paginate_feed(feed_items, page, per_page)

        except Exception as e:
            logger.error(f"Feed error for user {user_id}: {str(e)}")
            raise NotFoundError("Failed to get feed")

    @staticmethod
    def _get_cached_feed(user_id):
        """Get feed from Redis cache"""
        return redis_client.zrevrange(f"user:{user_id}:feed", 0, -1, withscores=True)

    @staticmethod
    def _hydrate_cached_items(cached_items):
        """Convert cached IDs to full objects"""
        with session_scope() as session:
            # Separate posts and products
            post_ids = []
            product_ids = []

            for item_id, _ in cached_items:
                if item_id.startswith("PST_"):
                    post_ids.append(item_id)
                elif item_id.startswith("PRD_"):
                    product_ids.append(item_id)

            # Fetch posts
            posts = (
                session.query(Post)
                .options(
                    joinedload(Post.seller).joinedload(Seller.user),
                    joinedload(Post.media),
                    joinedload(Post.tagged_products).joinedload(PostProduct.product),
                )
                .filter(
                    Post.id.in_(post_ids),
                    Post.status == PostStatus.ACTIVE,
                )
                .all()
                if post_ids
                else []
            )

            # Fetch products
            products = (
                session.query(Product)
                .options(joinedload(Product.seller), joinedload(Product.images))
                .filter(
                    Product.id.in_(product_ids),
                    Product.status == ProductStatus.ACTIVE,
                )
                .all()
                if product_ids
                else []
            )

            # Reconstruct feed items
            feed_items = []
            for item_id, score in cached_items:
                if item_id.startswith("PST_"):
                    post = next((p for p in posts if p.id == item_id), None)
                    if post:
                        feed_items.append(
                            {
                                "type": "post",
                                "data": post,
                                "score": score,
                                "created_at": datetime.fromtimestamp(score),
                            }
                        )
                else:
                    product = next((p for p in products if p.id == item_id), None)
                    if product:
                        feed_items.append(
                            {
                                "type": "product",
                                "data": product,
                                "score": score,
                                "created_at": datetime.fromtimestamp(score),
                            }
                        )

            return feed_items

    @staticmethod
    def _generate_fresh_feed(user_id):
        """Generate fresh feed from database sources"""
        # Get base content
        posts = FeedService._get_followed_posts(user_id)
        products = ProductService.get_recommended_products(user_id)
        trending = TrendingService.get_trending_content(user_id)

        # Score and combine
        feed_items = []
        feed_items.extend(FeedService._score_posts(posts, user_id))
        feed_items.extend(FeedService._score_products(products, user_id))
        feed_items.extend(trending)

        # Apply ranking and diversity
        ranked_items = FeedService._apply_ranking(feed_items)

        # Cache results
        FeedService._cache_feed(user_id, ranked_items)

        return ranked_items

    @staticmethod
    def _get_followed_posts(user_id):
        """Get posts from followed sellers"""
        with session_scope() as session:
            followed_sellers = (
                session.query(Seller.id)
                .join(Follow, Follow.followee_id == Seller.user_id)
                .filter(
                    Follow.follower_id == user_id,
                    Follow.follow_type == FollowType.CUSTOMER,
                )
                .subquery()
            )

            return (
                session.query(Post)
                .options(
                    joinedload(Post.seller).joinedload(Seller.user),
                    joinedload(Post.media),
                    joinedload(Post.tagged_products).joinedload(PostProduct.product),
                )
                .filter(
                    Post.seller_id.in_(followed_sellers),
                    Post.status == PostStatus.ACTIVE,
                )
                .order_by(Post.created_at.desc())
                .limit(100)
                .all()
            )

    @staticmethod
    def _score_posts(posts, user_id):
        """Calculate scores for posts"""
        return [
            {
                "type": "post",
                "data": post,
                "score": FeedService._calculate_post_score(post, user_id),
                "created_at": post.created_at,
            }
            for post in posts
        ]

    @staticmethod
    def _calculate_post_score(post, user_id):
        """Calculate composite score for a post"""
        score = 0

        # 1. Base score for followed accounts
        score += 15 if FeedService._is_from_followed_seller(post, user_id) else 5

        # 2. Engagement signals with logarithmic scaling
        score += math.log1p(post.like_count) * 2
        score += math.log1p(post.comment_count) * 1.5

        # 3. Recency decay (halflife of 3 days)
        hours_old = (datetime.utcnow() - post.created_at).total_seconds() / 3600
        score *= 0.5 ** (hours_old / 72)

        # 4. Personalization bonus
        if FeedService._matches_user_interests(post, user_id):
            score *= 1.5

        return score

    @staticmethod
    def _score_products(products, user_id):
        """Calculate scores for products"""
        return [
            {
                "type": "product",
                "data": product,
                "score": FeedService._calculate_product_score(product, user_id),
                "created_at": product.created_at,
            }
            for product in products
        ]

    @staticmethod
    def _calculate_product_score(product, user_id):
        """Updated scoring algorithm"""
        score = 0

        # 1. Base score
        score += 10

        # 2. Engagement signals
        score += math.log1p(product.view_count) * 1.2
        score += math.log1p(product.review_count) * 1.5

        # 3. Rating quality
        if product.average_rating >= 4:
            score += 10
        elif product.average_rating >= 3:
            score += 5

        # 4. Seller reputation
        if product.seller.verification_status == SellerVerificationStatus.VERIFIED:
            score += 5

        # 5. Personalization
        if FeedService._matches_user_preferences(product, user_id):
            score *= 1.5

        return score

    @staticmethod
    def _apply_ranking(items):
        """Apply ranking and diversity rules"""
        # Sort by score descending
        items.sort(key=lambda x: x["score"], reverse=True)

        # Apply diversity - don't show more than 3 similar items in a row
        ranked_items = []
        last_types = []

        for item in items:
            if len(last_types) >= 3 and all(t == item["type"] for t in last_types[-3:]):
                continue  # Skip to maintain diversity

            ranked_items.append(item)
            last_types.append(item["type"])

        return ranked_items

    @staticmethod
    def _cache_feed(user_id, feed_items):
        """Cache feed in Redis"""
        with redis_client.pipeline() as pipe:
            pipe.delete(f"user:{user_id}:feed")
            for item in feed_items:
                pipe.zadd(
                    f"user:{user_id}:feed",
                    {item["data"].id: int(item["created_at"].timestamp())},
                )
            pipe.expire(f"user:{user_id}:feed", 86400)  # 24h cache
            pipe.execute()

    @staticmethod
    def _paginate_feed(feed_items, page, per_page):
        """Paginate feed results for in-memory list"""
        from math import ceil

        total_items = len(feed_items)
        total_pages = ceil(total_items / per_page) if total_items else 0

        # Calculate offset
        offset = (page - 1) * per_page

        # Slice the list for pagination
        paginated_items = feed_items[offset : offset + per_page]

        return {
            "items": paginated_items,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_items": total_items,
                "total_pages": total_pages,
            },
        }

    @staticmethod
    def _is_from_followed_seller(post, user_id):
        """Check if post is from a followed seller"""
        # Implementation would query follow relationships
        # Can be optimized with cached follow data
        with session_scope() as session:
            return (
                session.query(Follow)
                .filter(
                    Follow.follower_id == user_id,
                    Follow.followee_id == post.seller.user_id,
                    Follow.follow_type == FollowType.CUSTOMER,
                )
                .first()
                is not None
            )

    @staticmethod
    def _matches_user_interests(post, user_id):
        """Check if post matches user's interests"""
        # Placeholder - would analyze:
        # - User's liked posts/categories
        # - Past engagement patterns
        return False

    @staticmethod
    def _matches_user_preferences(product, user_id):
        """Check if product matches user's preferences"""
        # Placeholder - would analyze:
        # - Purchase history
        # - Viewed products
        # - Saved items
        return False


class TrendingService:
    @staticmethod
    def get_trending_content(user_id=None, limit=5):
        """Get trending content personalized for user"""
        try:
            trending = []

            # Get globally popular posts
            post_ids = redis_client.zrevrange("popular_posts", 0, limit - 1)
            if post_ids:
                with session_scope() as session:
                    posts = (
                        session.query(Post)
                        .filter(Post.id.in_(post_ids))
                        .options(
                            joinedload(Post.seller).joinedload(Seller.user),
                            joinedload(Post.media),
                        )
                        .all()
                    )

                    trending.extend(
                        [
                            {
                                "type": "post",
                                "data": p,
                                "score": redis_client.zscore("popular_posts", p.id),
                                "created_at": p.created_at,
                            }
                            for p in posts
                        ]
                    )

            return trending

        except Exception as e:
            logger.error(f"Trending content error: {str(e)}")
            return []
