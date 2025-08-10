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
from app.media.services import media_service
from app.media.models import Media, SocialMediaPost
from app.categories.models import (
    ProductCategory,
    PostCategory,
    SellerCategory,
    NicheCategory,
    Category,
)

# app imports
from .models import (
    Post,
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
    PostCommentReaction,
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
                tags=data.get("tags", []),
                rules=data.get("rules", []),
                settings=data.get("settings", {}),
            )

            session.add(niche)
            session.flush()

            # Handle category relationships
            if "category_ids" in data and data["category_ids"]:
                for idx, category_id in enumerate(data["category_ids"]):
                    # Verify category exists
                    category = session.query(Category).get(category_id)
                    if not category:
                        raise ValidationError(f"Category {category_id} not found")

                    # Create niche category relationship
                    niche_category = NicheCategory(
                        niche_id=niche.id,
                        category_id=category_id,
                        is_primary=(idx == 0),  # First category is primary
                    )
                    session.add(niche_category)

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
                    joinedload(Niche.categories).joinedload(NicheCategory.category),
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

            # TODO: Implement proper Redis caching with serialization
            # For now, disable caching to fix Redis DataError

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
                    joinedload(NicheMembership.niche)
                    .joinedload(Niche.categories)
                    .joinedload(NicheCategory.category),
                )
                .order_by(NicheMembership.last_activity.desc())
            )

            paginator = Paginator(
                base_query, page=args.get("page", 1), per_page=args.get("per_page", 20)
            )
            result = paginator.paginate(args)

            # TODO: Implement proper Redis caching with serialization
            # For now, disable caching to fix Redis DataError

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

            if args.get("category_ids"):
                # Filter by multiple categories (OR logic)
                category_filters = []
                for category_id in args["category_ids"]:
                    category_filters.append(
                        Niche.categories.any(NicheCategory.category_id == category_id)
                    )
                if category_filters:
                    base_query = base_query.filter(db.or_(*category_filters))

            # Order by relevance (member count, activity)
            base_query = base_query.order_by(
                Niche.member_count.desc(),
                Niche.post_count.desc(),
                Niche.created_at.desc(),
            )

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

    @staticmethod
    def create_niche_post(
        niche_id: str, current_user: User, post_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a post in a specific niche/community"""
        user_id = current_user.id
        with session_scope() as session:
            # Check if user can post in this niche
            permission_check = NicheService.can_user_post_in_niche(niche_id, user_id)
            if not permission_check["can_post"]:
                raise ForbiddenError(permission_check["reason"])

            # Get niche and user
            niche = session.query(Niche).get(niche_id)
            user = session.query(User).get(user_id)

            # Create the post using PostService
            if user.is_seller:
                # For sellers, create post with seller_id
                seller = session.query(Seller).filter_by(user_id=user_id).first()
                if not seller:
                    raise ValidationError("Seller account not found")

                post = PostService.create_post(current_user, post_data)
            else:
                # For buyers, we need to handle this differently since posts are seller-based
                # For now, we'll create a special buyer post or use a different approach
                raise ValidationError("Buyer posts not yet implemented")

            # Create the niche post association
            niche_post = NichePost(
                niche_id=niche_id,
                post_id=post.id,
                status=PostStatus.ACTIVE,
                is_approved=not niche.require_approval,  # Auto-approve if not required
            )

            # If approval is required, set status to pending
            if niche.require_approval:
                niche_post.is_approved = False
                niche_post.status = PostStatus.DRAFT

            session.add(niche_post)

            # Update niche post count
            niche.post_count += 1

            # Update user's post count in this niche
            membership = (
                session.query(NicheMembership)
                .filter_by(niche_id=niche_id, user_id=user_id, is_active=True)
                .first()
            )
            if membership:
                membership.post_count += 1
                membership.last_activity = datetime.utcnow()

            # Cache invalidation
            NicheService._invalidate_niche_cache(niche_id)
            NicheService._invalidate_user_cache(user_id)

            return {
                "post": post,
                "niche_post": niche_post,
                "requires_approval": niche.require_approval,
                "is_approved": niche_post.is_approved,
            }

    @staticmethod
    def get_niche_posts(niche_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get posts from a specific niche"""
        with session_scope() as session:
            # Check niche exists and user has access
            niche = session.query(Niche).get(niche_id)
            if not niche:
                raise NotFoundError("Community not found")

            # Check visibility
            user_id = args.get("user_id")
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

            # Build query for niche posts
            base_query = (
                session.query(NichePost)
                .filter(
                    NichePost.niche_id == niche_id,
                    NichePost.status == PostStatus.ACTIVE,
                    NichePost.is_approved == True,
                )
                .options(
                    joinedload(NichePost.post)
                    .joinedload(Post.seller)
                    .joinedload(Seller.user),
                    joinedload(NichePost.post).joinedload(Post.social_media),
                    joinedload(NichePost.post)
                    .joinedload(Post.tagged_products)
                    .joinedload(PostProduct.product),
                    joinedload(NichePost.post).joinedload(Post.likes),
                    joinedload(NichePost.post).joinedload(Post.comments),
                )
                .order_by(NichePost.created_at.desc())
            )

            # Apply filters
            if args.get("pinned_only"):
                base_query = base_query.filter(NichePost.is_pinned == True)

            if args.get("featured_only"):
                base_query = base_query.filter(NichePost.is_featured == True)

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
    def approve_niche_post(niche_id: str, post_id: str, moderator_id: str) -> NichePost:
        """Approve a pending post in a niche (moderators only)"""
        with session_scope() as session:
            # Check moderator permissions
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

            # Get the niche post
            niche_post = (
                session.query(NichePost)
                .filter_by(niche_id=niche_id, post_id=post_id)
                .first()
            )

            if not niche_post:
                raise NotFoundError("Post not found in this community")

            if niche_post.is_approved:
                raise ConflictError("Post is already approved")

            # Approve the post
            niche_post.is_approved = True
            niche_post.status = PostStatus.ACTIVE
            niche_post.moderated_by = moderator_id
            niche_post.moderated_at = datetime.utcnow()

            # Update the main post status if it was in draft
            post = session.query(Post).get(post_id)
            if post and post.status == PostStatus.DRAFT:
                post.status = PostStatus.ACTIVE

            # Notify the post creator
            if post and post.seller.user_id != moderator_id:
                from app.notifications.services import NotificationService

                NotificationService.create_notification(
                    user_id=post.seller.user_id,
                    notification_type=NotificationType.NICHE_POST_APPROVED,
                    reference_type="post",
                    reference_id=post_id,
                    metadata_={
                        "niche_id": niche_id,
                        "niche_name": niche_post.niche.name,
                    },
                )

            return niche_post

    @staticmethod
    def reject_niche_post(
        niche_id: str, post_id: str, moderator_id: str, reason: str
    ) -> NichePost:
        """Reject a pending post in a niche (moderators only)"""
        with session_scope() as session:
            # Check moderator permissions
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

            # Get the niche post
            niche_post = (
                session.query(NichePost)
                .filter_by(niche_id=niche_id, post_id=post_id)
                .first()
            )

            if not niche_post:
                raise NotFoundError("Post not found in this community")

            if niche_post.is_approved:
                raise ConflictError("Post is already approved")

            # Reject the post
            niche_post.is_approved = False
            niche_post.status = PostStatus.DELETED
            niche_post.moderated_by = moderator_id
            niche_post.moderated_at = datetime.utcnow()

            # Notify the post creator
            post = session.query(Post).get(post_id)
            if post and post.seller.user_id != moderator_id:
                from app.notifications.services import NotificationService

                NotificationService.create_notification(
                    user_id=post.seller.user_id,
                    notification_type=NotificationType.NICHE_POST_REJECTED,
                    reference_type="post",
                    reference_id=post_id,
                    metadata_={
                        "niche_id": niche_id,
                        "niche_name": niche_post.niche.name,
                        "reason": reason,
                    },
                )

            return niche_post

    @staticmethod
    def update_niche(niche_id: str, user_id: str, data: Dict[str, Any]) -> Niche:
        """Update niche details (owner only)"""
        with session_scope() as session:
            niche = session.query(Niche).get(niche_id)
            if not niche:
                raise NotFoundError("Community not found")

            # Check ownership
            membership = (
                session.query(NicheMembership)
                .filter_by(
                    niche_id=niche_id, user_id=user_id, role=NicheMembershipRole.OWNER
                )
                .first()
            )
            if not membership:
                raise ForbiddenError("Only community owners can update settings")

            # Update fields
            if data.get("name"):
                # Check if new name would create duplicate slug
                new_slug = NicheService._generate_slug(data["name"])
                existing = (
                    session.query(Niche)
                    .filter(Niche.slug == new_slug, Niche.id != niche_id)
                    .first()
                )
                if existing:
                    raise ConflictError("A community with this name already exists")

                niche.name = data["name"]
                niche.slug = new_slug

            if data.get("description"):
                niche.description = data["description"]

            if data.get("visibility"):
                niche.visibility = NicheVisibility(data["visibility"])

            if data.get("allow_buyer_posts") is not None:
                niche.allow_buyer_posts = data["allow_buyer_posts"]

            if data.get("allow_seller_posts") is not None:
                niche.allow_seller_posts = data["allow_seller_posts"]

            if data.get("require_approval") is not None:
                niche.require_approval = data["require_approval"]

            if data.get("max_members"):
                niche.max_members = data["max_members"]

            if data.get("category_ids") is not None:
                # Remove existing category relationships
                session.query(NicheCategory).filter_by(niche_id=niche_id).delete()

                # Add new category relationships
                for idx, category_id in enumerate(data["category_ids"]):
                    # Verify category exists
                    category = session.query(Category).get(category_id)
                    if not category:
                        raise ValidationError(f"Category {category_id} not found")

                    # Create niche category relationship
                    niche_category = NicheCategory(
                        niche_id=niche_id,
                        category_id=category_id,
                        is_primary=(idx == 0),  # First category is primary
                    )
                    session.add(niche_category)

            if data.get("tags") is not None:
                niche.tags = data["tags"]

            if data.get("rules") is not None:
                niche.rules = data["rules"]

            if data.get("settings") is not None:
                niche.settings = data["settings"]

            # Cache invalidation
            NicheService._invalidate_niche_cache(niche_id)

            return niche

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
    def create_post(current_user, post_data):
        seller_id = current_user.seller_account.id
        try:
            with session_scope() as session:
                # Verify seller exists
                seller = session.query(Seller).get(seller_id)
                if not seller:
                    raise NotFoundError("Seller not found")

                # Set status from request or default to draft
                status = PostStatus(post_data.get("status", "draft"))

                post = Post(
                    seller_id=seller_id,
                    caption=post_data.get("caption"),
                    status=status,
                    tags=post_data.get("tags", []),
                )
                session.add(post)
                session.flush()

                # Handle category relationships
                if "category_ids" in post_data and post_data["category_ids"]:
                    for idx, category_id in enumerate(post_data["category_ids"]):
                        # Verify category exists
                        category = session.query(Category).get(category_id)
                        if not category:
                            raise ValidationError(f"Category {category_id} not found")

                        # Create post category relationship
                        post_category = PostCategory(
                            post_id=post.id,
                            category_id=category_id,
                            is_primary=(idx == 0),  # First category is primary
                        )
                        session.add(post_category)

                # Handle media linking if provided
                if "media_ids" in post_data and post_data["media_ids"]:
                    for idx, media_id in enumerate(post_data["media_ids"]):
                        # Verify media exists and belongs to seller
                        media = session.query(Media).get(media_id)
                        if not media:
                            raise ValidationError(f"Media {media_id} not found")

                        if media.user_id != current_user.id:
                            raise ValidationError(
                                f"Media {media_id} does not belong to you"
                            )

                        # Create social media post relationship
                        social_post = SocialMediaPost(
                            post_id=post.id,
                            media_id=media_id,
                            sort_order=idx,
                            platform=None,  # Will be set when posting to specific platforms
                            post_type=None,  # Will be set when posting to specific platforms
                            aspect_ratio=None,
                        )
                        session.add(social_post)

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
            logger.warning(f"Redis error while creating post: {str(e)}", exc_info=True)

    @staticmethod
    def get_post(post_id):
        try:
            with session_scope() as session:
                post = (
                    session.query(Post)
                    .options(
                        joinedload(Post.seller).joinedload(Seller.user),
                        joinedload(Post.social_media),
                        joinedload(Post.tagged_products).joinedload(
                            PostProduct.product
                        ),
                        joinedload(Post.niche_posts).joinedload(NichePost.niche),
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
    def get_post_with_niche_context(post_id):
        """Get post with niche context if it's posted in a niche"""
        try:
            with session_scope() as session:
                post = (
                    session.query(Post)
                    .options(
                        joinedload(Post.seller).joinedload(Seller.user),
                        joinedload(Post.social_media),
                        joinedload(Post.tagged_products).joinedload(
                            PostProduct.product
                        ),
                        joinedload(Post.niche_posts).joinedload(NichePost.niche),
                    )
                    .get(post_id)
                )
                if not post:
                    raise NotFoundError("Post not found")

                # Add niche context if available
                niche_context = PostService._get_niche_context(post)
                if niche_context:
                    post.niche_context = niche_context

                return post
        except SQLAlchemyError as e:
            logger.error(f"Error fetching post {post_id}: {str(e)}")
            raise NotFoundError("Failed to fetch post")

    @staticmethod
    def _get_niche_context(post):
        """Get niche context for a post"""
        if hasattr(post, "niche_posts") and post.niche_posts:
            niche_post = post.niche_posts[0]  # Assuming one niche per post for now
            return {
                "niche_id": niche_post.niche_id,
                "niche_name": niche_post.niche.name,
                "niche_slug": niche_post.niche.slug,
                "is_pinned": niche_post.is_pinned,
                "is_featured": niche_post.is_featured,
                "is_approved": niche_post.is_approved,
                "niche_likes": niche_post.niche_likes,
                "niche_comments": niche_post.niche_comments,
                "niche_visibility": niche_post.niche.visibility.value,
            }
        return None

    @staticmethod
    def _enhance_posts_with_niche_context(posts):
        """Add niche context to a list of posts"""
        for post in posts:
            niche_context = PostService._get_niche_context(post)
            if niche_context:
                post.niche_context = niche_context
        return posts

    @staticmethod
    def get_seller_posts(seller_id, page=1, per_page=20):
        """Get paginated posts by seller"""
        with session_scope() as session:
            base_query = (
                session.query(Post)
                .filter(Post.seller_id == seller_id, Post.status == PostStatus.ACTIVE)
                .options(
                    joinedload(Post.social_media),
                    joinedload(Post.tagged_products).joinedload(PostProduct.product),
                    # Add these to load the relationships needed for counting
                    joinedload(Post.likes),
                    joinedload(Post.comments),
                    # Add niche posts relationship
                    joinedload(Post.niche_posts).joinedload(NichePost.niche),
                )
            )
            paginator = Paginator(base_query, page=page, per_page=per_page)
            result = paginator.paginate({})  # Pass empty dict if no filters

            # Enhance posts with niche context
            posts = PostService._enhance_posts_with_niche_context(result["items"])

            return {
                "items": posts,
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

                # Get post owner and user info for notifications
                post = session.query(Post).get(post_id)
                user = session.query(User).get(user_id)

                if post.seller.user_id != user_id:  # Don't notify for self-likes
                    from app.notifications.services import NotificationService

                    NotificationService.create_notification(
                        user_id=post.seller.user_id,
                        notification_type=NotificationType.POST_LIKE,
                        actor_id=user_id,
                        reference_type="post",
                        reference_id=post_id,
                    )

                # Queue async real-time event (non-blocking)
                try:
                    from app.realtime.event_manager import EventManager

                    EventManager.emit_to_post(
                        post_id,
                        "post_liked",
                        {
                            "post_id": post_id,
                            "user_id": user_id,
                            "username": user.username if user else "Unknown",
                            "like_count": redis_client.zcard(f"post:{post_id}:likes"),
                        },
                    )
                except Exception as e:
                    logger.warning(f"Failed to queue post_liked event: {e}")

                return like
        except SQLAlchemyError as e:
            logger.error(f"Error liking post: {str(e)}")
            raise ConflictError("Failed to like post")
        except (RedisError, RedisConnectionError) as e:
            logger.warning(f"Redis error while liking post: {str(e)}", exc_info=True)

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

                    # Queue async real-time event (non-blocking)
                    try:
                        from app.realtime.event_manager import EventManager

                        user = session.query(User).get(user_id)
                        EventManager.emit_to_post(
                            post_id,
                            "post_unliked",
                            {
                                "post_id": post_id,
                                "user_id": user_id,
                                "username": user.username if user else "Unknown",
                                "like_count": redis_client.zcard(
                                    f"post:{post_id}:likes"
                                ),
                            },
                        )
                    except Exception as e:
                        logger.warning(f"Failed to queue post_unliked event: {e}")

        except SQLAlchemyError as e:
            logger.error(f"Error unliking post: {str(e)}")
            raise ConflictError("Failed to unlike post")
        except (RedisError, RedisConnectionError) as e:
            logger.warning(f"Redis error while unliking post: {str(e)}", exc_info=True)

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
                if "media_files" in update_data:
                    # Clear existing social media posts
                    from app.media.models import SocialMediaPost

                    session.query(SocialMediaPost).filter_by(post_id=post_id).delete()

                    # Add new media
                    for media_data in update_data["media_files"]:
                        if "media_id" in media_data:
                            social_post = SocialMediaPost(
                                post_id=post.id,
                                media_id=media_data["media_id"],
                                platform=media_data.get("platform"),
                                post_type=media_data.get("post_type"),
                                sort_order=media_data.get("sort_order", 0),
                                optimized_for_platform=True,
                            )
                            session.add(social_post)

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
            logger.warning(
                f"Redis error while changing post status: {str(e)}", exc_info=True
            )

    @staticmethod
    def get_seller_drafts(seller_id, page=1, per_page=20):
        """Get seller's draft posts"""
        with session_scope() as session:
            base_query = (
                session.query(Post)
                .filter(Post.seller_id == seller_id, Post.status == PostStatus.DRAFT)
                .options(
                    joinedload(Post.social_media),
                    joinedload(Post.tagged_products).joinedload(PostProduct.product),
                    joinedload(Post.categories).joinedload(PostCategory.category),
                )
            )
            paginator = Paginator(base_query, page=page, per_page=per_page)
            result = paginator.paginate({})
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
    def get_seller_archived(seller_id, page=1, per_page=20):
        """Get seller's archived posts"""
        with session_scope() as session:
            base_query = (
                session.query(Post)
                .filter(Post.seller_id == seller_id, Post.status == PostStatus.ARCHIVED)
                .options(
                    joinedload(Post.social_media),
                    joinedload(Post.tagged_products).joinedload(PostProduct.product),
                    joinedload(Post.categories).joinedload(PostCategory.category),
                )
            )
            paginator = Paginator(base_query, page=page, per_page=per_page)
            result = paginator.paginate({})
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
            logger.warning(f"Redis error while adding comment: {str(e)}", exc_info=True)

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
            result = paginator.paginate({})
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
    def get_posts(args):
        """Get paginated posts with filtering"""
        with session_scope() as session:
            base_query = (
                session.query(Post)
                .filter(Post.status == PostStatus.ACTIVE)
                .options(
                    joinedload(Post.seller).joinedload(Seller.user),
                    joinedload(Post.social_media),
                    joinedload(Post.tagged_products).joinedload(PostProduct.product),
                    joinedload(Post.likes),
                    joinedload(Post.comments),
                    # Add niche posts relationship
                    joinedload(Post.niche_posts).joinedload(NichePost.niche),
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

            # Enhance posts with niche context
            posts = PostService._enhance_posts_with_niche_context(result["items"])

            return {
                "items": posts,
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
        """Toggle like on post using existing like_post/unlike_post services"""
        try:
            with session_scope() as session:
                # Check if like already exists
                existing_like = (
                    session.query(PostLike)
                    .filter_by(user_id=user_id, post_id=post_id)
                    .first()
                )

                if existing_like:
                    # Unlike using existing service
                    PostService.unlike_post(user_id, post_id)
                    return {"liked": False, "message": "Post unliked"}
                else:
                    # Like using existing service
                    PostService.like_post(user_id, post_id)
                    return {"liked": True, "message": "Post liked"}

        except Exception as e:
            logger.error(f"Error toggling like: {str(e)}")
            raise ConflictError("Failed to toggle like")

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

    @staticmethod
    def post_exists(post_id: str) -> bool:
        """Check if a post exists"""
        try:
            with session_scope() as session:
                post = session.query(Post).filter(Post.id == post_id).first()
                return post is not None
        except Exception as e:
            logger.error(f"Error checking if post exists: {e}")
            return False

    @staticmethod
    def add_post_media(
        post_id: str,
        file_stream,
        filename: str,
        user_id: str,
        platform: str = None,
        post_type: str = None,
        aspect_ratio: str = None,
    ):
        """Add media to a social media post"""
        try:
            from io import BytesIO
            from app.media.models import SocialMediaPost

            # Ensure file_stream is BytesIO
            if not isinstance(file_stream, BytesIO):
                file_stream = BytesIO(file_stream.read())

            with session_scope() as session:
                # Verify post exists and user owns it
                post = session.query(Post).get(post_id)
                if not post:
                    raise NotFoundError("Post not found")

                if post.seller.user_id != user_id:
                    raise ForbiddenError("You can only add media to your own posts")

                # 1. Upload media using updated media service (returns only media object)
                media = media_service.upload_image(
                    file_stream=file_stream,
                    filename=filename,
                    user_id=user_id,
                    alt_text=f"Post media for {post_id}",
                    caption="Social media post image",
                )

                # 2. Create social media post relationship
                social_post = SocialMediaPost(
                    post_id=post_id,
                    media_id=media.id,
                    platform=platform,
                    post_type=post_type,
                    aspect_ratio=aspect_ratio,
                    optimized_for_platform=True,
                )

                session.add(social_post)
                session.flush()

                return social_post

        except Exception as e:
            logger.error(f"Failed to add post media: {e}")
            raise ValidationError(f"Failed to add post media: {str(e)}")

    @staticmethod
    def get_post_media(post_id: str):
        """Get all media for a social media post"""
        with session_scope() as session:
            from app.media.models import SocialMediaPost

            # Get social media posts and filter out those with soft-deleted media
            social_posts = (
                session.query(SocialMediaPost)
                .filter_by(post_id=post_id)
                .order_by(SocialMediaPost.sort_order)
                .all()
            )

            # Filter out posts with soft-deleted media
            active_posts = []
            for post in social_posts:
                if post.media and not post.media.is_deleted:
                    active_posts.append(post)

            return active_posts

    @staticmethod
    def delete_post_media(media_id: int, user_id: str):
        """Delete media from a social media post"""
        try:
            with session_scope() as session:
                from app.media.models import SocialMediaPost

                social_post = session.query(SocialMediaPost).get(media_id)
                if not social_post:
                    raise NotFoundError("Post media not found")

                # Verify user owns the post
                if social_post.post.seller.user_id != user_id:
                    raise ForbiddenError(
                        "You can only delete media from your own posts"
                    )

                # Get the media object
                media = social_post.media
                if media:
                    # Soft delete media using media service
                    success = media_service.delete_media(media, hard_delete=False)
                    if not success:
                        logger.warning(f"Failed to soft delete media {media.id}")

                    # Update the media object in the session
                    session.merge(media)

                # Delete social media post relationship
                session.delete(social_post)
                session.flush()

                return {"success": True, "message": "Post media deleted"}

        except Exception as e:
            logger.error(f"Failed to delete post media: {e}")
            raise ValidationError(f"Failed to delete post media: {str(e)}")

    @staticmethod
    def optimize_post_for_social_media(post_id: str, platform: str, post_type: str):
        """Get optimized media URLs for social media platforms"""
        with session_scope() as session:
            from app.media.models import SocialMediaPost

            social_posts = (
                session.query(SocialMediaPost).filter_by(post_id=post_id).all()
            )

            optimized_media = []
            for social_post in social_posts:
                if social_post.media:
                    result = media_service.optimize_for_social_media(
                        media=social_post.media, platform=platform, post_type=post_type
                    )
                    optimized_media.append(
                        {
                            "media_id": social_post.media.id,
                            "original_url": result.get("original"),
                            "optimized_url": result.get("optimized"),
                            "platform": platform,
                            "post_type": post_type,
                        }
                    )

            return optimized_media


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

                # Queue async real-time event (non-blocking)
                try:
                    from app.realtime.event_manager import EventManager

                    user = session.query(User).get(user_id)
                    EventManager.emit_to_product(
                        product_id,
                        "review_added",
                        {
                            "product_id": product_id,
                            "review_id": review.id,
                            "user_id": user_id,
                            "username": user.username if user else "Unknown",
                            "rating": data.get("rating"),
                            "review_count": int(
                                redis_client.hget(redis_key, "review_count")
                            ),
                            "avg_rating": float(
                                redis_client.hget(redis_key, "avg_rating") or 0
                            ),
                            "is_verified": data.get("is_verified", False),
                        },
                    )
                except Exception as e:
                    logger.warning(f"Failed to queue review_added event: {e}")

                return review
        except Exception as e:
            logger.error(f"Error adding review: {str(e)}")
            raise APIError("Failed to add review", 500)
        except SQLAlchemyError as e:
            logger.error(f"Error adding review: {str(e)}")
            raise ConflictError("Failed to add review")
        except (RedisError, RedisConnectionError) as e:
            logger.warning(f"Redis error while adding review: {str(e)}", exc_info=True)

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

                # Queue async real-time event (non-blocking)
                try:
                    from app.realtime.event_manager import EventManager

                    user = session.query(User).get(user_id)
                    EventManager.emit_to_product(
                        review.product_id,
                        "review_upvoted",
                        {
                            "review_id": review_id,
                            "product_id": review.product_id,
                            "user_id": user_id,
                            "username": user.username if user else "Unknown",
                            "upvotes": review.upvotes,
                            "review_author_id": review.user_id,
                        },
                    )
                except Exception as e:
                    logger.warning(f"Failed to queue review_upvoted event: {e}")

                return review
        except SQLAlchemyError as e:
            logger.error(f"Error upvoting review: {str(e)}")
            raise ConflictError("Failed to upvote review")
        except (RedisError, RedisConnectionError) as e:
            logger.warning(
                f"Redis error while upvoting review: {str(e)}", exc_info=True
            )

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
            result = paginator.paginate({})
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
            logger.warning(
                f"Redis error while unfollowing user: {str(e)}", exc_info=True
            )


class FeedService:
    """Enhanced feed service with personalization and real-time updates"""

    # Cache keys with user-specific prefixes
    CACHE_KEYS = {
        "user_feed": "feed:user:{user_id}:{feed_type}",
        "user_interests": "user:{user_id}:interests",
        "user_preferences": "user:{user_id}:preferences",
        "trending_content": "trending:content:{content_type}",
        "feed_metadata": "feed:metadata:{user_id}",
    }

    # Feed types for different user contexts
    FEED_TYPES = {
        "personalized": "personalized",
        "trending": "trending",
        "following": "following",
        "discover": "discover",
        "niche": "niche:{niche_id}",
    }

    @staticmethod
    def get_hybrid_feed(
        user_id, page=1, per_page=20, feed_type="personalized", **kwargs
    ):
        """Get personalized hybrid feed with real-time updates"""
        try:
            # Check cache first
            cached_feed = FeedService._get_cached_feed(user_id, feed_type)
            if cached_feed and not kwargs.get("force_refresh"):
                # Hydrate cached items before pagination
                hydrated_items = FeedService._hydrate_cached_items(cached_feed)
                return FeedService._paginate_feed(hydrated_items, page, per_page)

            # Generate fresh feed
            feed_items = FeedService._generate_fresh_feed(user_id, feed_type, **kwargs)

            # Cache the feed
            FeedService._cache_feed(user_id, feed_items, feed_type)

            # Hydrate and paginate fresh feed
            hydrated_items = FeedService._hydrate_cached_items(feed_items)
            return FeedService._paginate_feed(hydrated_items, page, per_page)

        except Exception as e:
            logger.error(f"Error getting feed for user {user_id}: {str(e)}")
            # Fallback to trending content
            return FeedService._get_fallback_feed(page, per_page)

    @staticmethod
    def _get_cached_feed(user_id, feed_type="personalized"):
        """Get cached feed with user-specific key"""
        cache_key = FeedService.CACHE_KEYS["user_feed"].format(
            user_id=user_id, feed_type=feed_type
        )

        try:
            cached = redis_client.get(cache_key)
            if cached:
                import json

                return json.loads(cached)
        except RedisError as e:
            logger.warning(f"Redis error getting cached feed: {str(e)}")
        except Exception as e:
            logger.warning(f"Error deserializing cached feed: {str(e)}")

        return None

    @staticmethod
    def _hydrate_cached_items(cached_items):
        """Enhanced hydration with better error handling and performance"""
        if not cached_items:
            return []

        try:
            # Parse cached items
            if isinstance(cached_items, str):
                import json

                cached_items = json.loads(cached_items)

            # Separate posts and products for batch loading
            post_ids = []
            product_ids = []

            for item in cached_items:
                if isinstance(item, dict):
                    item_id = item.get("id")
                    if item_id and item_id.startswith("PST_"):
                        post_ids.append(item_id)
                    elif item_id and item_id.startswith("PRD_"):
                        product_ids.append(item_id)
                elif isinstance(item, str):
                    if item.startswith("PST_"):
                        post_ids.append(item)
                    elif item.startswith("PRD_"):
                        product_ids.append(item)

            # Batch load posts and products
            posts = []
            products = []

            if post_ids:
                with session_scope() as session:
                    posts = (
                        session.query(Post)
                        .options(
                            joinedload(Post.seller).joinedload(Seller.user),
                            joinedload(Post.social_media),
                            joinedload(Post.likes),
                            joinedload(Post.comments),
                            joinedload(Post.niche_posts).joinedload(NichePost.niche),
                        )
                        .filter(
                            Post.id.in_(post_ids),
                            Post.status == PostStatus.ACTIVE,
                        )
                        .all()
                    )

            if product_ids:
                with session_scope() as session:
                    products = (
                        session.query(Product)
                        .options(
                            joinedload(Product.seller).joinedload(Seller.user),
                            joinedload(Product.images),
                            joinedload(Product.reviews),
                        )
                        .filter(
                            Product.id.in_(product_ids),
                            Product.status == Product.Status.ACTIVE,
                        )
                        .all()
                    )

            # Create lookup dictionaries
            posts_dict = {post.id: post for post in posts}
            products_dict = {product.id: product for product in products}

            # Hydrate feed items
            hydrated_items = []

            for item in cached_items:
                # Handle different item formats
                if isinstance(item, dict):
                    item_id = item.get("id")
                    score = item.get("score", 0)
                elif isinstance(item, str):
                    # Handle string items (legacy format)
                    item_id = item
                    score = 0
                else:
                    # Handle bytes or other types
                    item_id = str(item)
                    score = 0

                if not item_id:
                    continue

                # Handle bytes from Redis
                if isinstance(item_id, bytes):
                    item_id = item_id.decode("utf-8")

                if item_id.startswith("PST_"):
                    post = posts_dict.get(item_id)
                    if post:
                        hydrated_items.append(
                            {
                                "id": post.id,
                                "type": "post",
                                "caption": post.caption,
                                "seller": {
                                    "id": post.seller.id,
                                    "shop_name": post.seller.shop_name,
                                    "user": {
                                        "id": post.seller.user.id,
                                        "username": post.seller.user.username,
                                        "profile_picture": post.seller.user.profile_picture,
                                    },
                                },
                                "media": [
                                    {
                                        "url": m.media.get_url(),
                                        "type": m.media.media_type.value,
                                        "platform": m.platform,
                                        "post_type": m.post_type,
                                        "aspect_ratio": m.aspect_ratio,
                                        "optimized_for_platform": m.optimized_for_platform,
                                    }
                                    for m in post.social_media
                                ],
                                "likes_count": len(post.likes),
                                "comments_count": len(post.comments),
                                "created_at": post.created_at.isoformat(),
                                "score": score,
                                "niche": {
                                    "id": post.niche_posts[0].niche.id,
                                    "name": post.niche_posts[0].niche.name,
                                    "slug": post.niche_posts[0].niche.slug,
                                    "visibility": post.niche_posts[
                                        0
                                    ].niche.visibility.value,
                                    "is_pinned": post.niche_posts[0].is_pinned,
                                    "is_featured": post.niche_posts[0].is_featured,
                                    "niche_likes": post.niche_posts[0].niche_likes,
                                    "niche_comments": post.niche_posts[
                                        0
                                    ].niche_comments,
                                }
                                if post.niche_posts
                                else None,
                            }
                        )

                elif item_id.startswith("PRD_"):
                    product = products_dict.get(item_id)
                    if product:
                        hydrated_items.append(
                            {
                                "id": product.id,
                                "type": "product",
                                "name": product.name,
                                "description": product.description,
                                "price": float(product.price),
                                "seller": {
                                    "id": product.seller.id,
                                    "shop_name": product.seller.shop_name,
                                    "user": {
                                        "id": product.seller.user.id,
                                        "username": product.seller.user.username,
                                        "profile_picture": product.seller.user.profile_picture,
                                    },
                                },
                                "images": [
                                    {
                                        "url": m.media.get_url(),
                                        "type": m.media.media_type.value,
                                        "sort_order": m.sort_order,
                                        "is_featured": m.is_featured,
                                        "alt_text": m.alt_text,
                                    }
                                    for m in product.images
                                ],
                                "rating": product.average_rating,
                                "reviews_count": len(product.reviews),
                                "created_at": product.created_at.isoformat(),
                                "score": score,
                            }
                        )

            return hydrated_items

        except Exception as e:
            logger.error(f"Error hydrating cached items: {str(e)}")
            return []

    @staticmethod
    def _generate_fresh_feed(user_id, feed_type="personalized", **kwargs):
        """Generate fresh personalized feed with enhanced algorithms"""
        try:
            feed_items = []

            if feed_type == "personalized":
                # Get user interests and preferences
                user_interests = FeedService._get_user_interests(user_id)
                user_preferences = FeedService._get_user_preferences(user_id)

                # Get followed content
                followed_items = FeedService._get_followed_content(user_id)
                feed_items.extend(followed_items)

                # Get content from engaged sellers (NEW!)
                engaged_items = FeedService._get_engaged_seller_content(user_id)
                feed_items.extend(engaged_items)

                # Get trending content based on user interests
                trending_items = FeedService._get_trending_by_interests(
                    user_id, user_interests
                )
                feed_items.extend(trending_items)

                # Get discover content
                discover_items = FeedService._get_discover_content(
                    user_id, user_preferences
                )
                feed_items.extend(discover_items)

            elif feed_type == "trending":
                # Pure trending content
                trending_content = FeedService._get_trending_content()
                feed_items.extend(trending_content)

            elif feed_type == "following":
                # Only followed content
                followed_items = FeedService._get_followed_content(user_id)
                feed_items.extend(followed_items)

            elif feed_type == "discover":
                # --- Discover Feed Implementation ---
                # 1. Get trending content (platform-wide, not just user interests)
                trending_items = FeedService._get_trending_content()
                # 2. Get diverse content based on _get_discover_content (using broad preferences)
                user_preferences = FeedService._get_user_preferences(user_id)
                discover_items = FeedService._get_discover_content(
                    user_id, user_preferences
                )
                # 3. Optionally, add more exploratory content (e.g., random/new sellers/products)
                # For now, combine trending and discover, deduplicate by id
                all_items = trending_items + discover_items
                seen_ids = set()
                unique_items = []
                for item in all_items:
                    if item["id"] not in seen_ids:
                        unique_items.append(item)
                        seen_ids.add(item["id"])
                # 4. Apply lighter personalization (time decay, diversity/freshness)
                scored_items = FeedService._apply_personalization_scoring(
                    unique_items, user_id
                )
                final_items = FeedService._apply_diversity_and_freshness(scored_items)
                return final_items

            elif feed_type.startswith("niche:"):
                # Niche-specific content
                niche_id = feed_type.split(":")[1]
                niche_items = FeedService._get_niche_content(niche_id, user_id)
                feed_items.extend(niche_items)

            # Apply personalization scoring
            scored_items = FeedService._apply_personalization_scoring(
                feed_items, user_id
            )

            # Apply diversity and freshness
            final_items = FeedService._apply_diversity_and_freshness(scored_items)

            return final_items

        except Exception as e:
            logger.error(f"Error generating fresh feed: {str(e)}")
            return FeedService._get_fallback_feed()

    @staticmethod
    def _get_user_interests(user_id):
        """Get user interests from cache or calculate"""
        cache_key = FeedService.CACHE_KEYS["user_interests"].format(user_id=user_id)

        try:
            cached = redis_client.get(cache_key)
            if cached:
                import json

                return json.loads(cached)
        except RedisError:
            pass
        except Exception:
            pass

        # Calculate user interests based on behavior
        interests = FeedService._calculate_user_interests(user_id)

        # Cache for 1 hour
        try:
            import json

            redis_client.setex(cache_key, 3600, json.dumps(interests))
        except RedisError:
            pass
        except Exception:
            pass

        return interests

    @staticmethod
    def _calculate_user_interests(user_id):
        """Calculate user interests based on behavior"""
        with session_scope() as session:
            # Get user's liked posts categories
            liked_categories = (
                session.query(PostCategory.category_id)
                .join(Post, Post.id == PostCategory.post_id)
                .join(PostLike, Post.id == PostLike.post_id)
                .filter(PostLike.user_id == user_id)
                .distinct()
                .all()
            )

            # Get user's viewed products categories
            viewed_categories = (
                session.query(ProductCategory.category_id)
                .join(Product, Product.id == ProductCategory.product_id)
                .join(ProductView, Product.id == ProductView.product_id)
                .filter(ProductView.user_id == user_id)
                .distinct()
                .all()
            )

            # Get user's followed sellers categories
            followed_categories = (
                session.query(SellerCategory.category_id)
                .join(Seller, Seller.id == SellerCategory.seller_id)
                .join(Follow, Seller.user_id == Follow.followee_id)
                .filter(Follow.follower_id == user_id)
                .distinct()
                .all()
            )

            # Combine and weight interests
            interests = {}

            for (category_id,) in liked_categories:
                if category_id:  # Only add if category_id is not None
                    interests[category_id] = interests.get(category_id, 0) + 3

            for (category_id,) in viewed_categories:
                if category_id:  # Only add if category_id is not None
                    interests[category_id] = interests.get(category_id, 0) + 2

            for (category,) in followed_categories:
                if category:  # Only add if category is not None
                    interests[category] = interests.get(category, 0) + 4

            return interests

    @staticmethod
    def _get_user_preferences(user_id):
        """Get user preferences for content discovery"""
        cache_key = FeedService.CACHE_KEYS["user_preferences"].format(user_id=user_id)

        try:
            cached = redis_client.get(cache_key)
            if cached:
                import json

                return json.loads(cached)
        except RedisError:
            pass
        except Exception:
            pass

        # Calculate preferences based on user behavior
        preferences = FeedService._calculate_user_preferences(user_id)

        # Cache for 2 hours
        try:
            import json

            redis_client.setex(cache_key, 7200, json.dumps(preferences))
        except RedisError:
            pass
        except Exception:
            pass

        return preferences

    @staticmethod
    def _calculate_user_preferences(user_id):
        """Calculate user preferences for content discovery"""
        with session_scope() as session:
            # Get user's activity patterns
            recent_likes = (
                session.query(PostLike)
                .filter(PostLike.user_id == user_id)
                .order_by(PostLike.created_at.desc())
                .limit(50)
                .all()
            )

            recent_views = (
                session.query(ProductView)
                .filter(ProductView.user_id == user_id)
                .order_by(ProductView.created_at.desc())
                .limit(50)
                .all()
            )

            # Analyze patterns
            preferences = {
                "content_ratio": 0.5,  # Default 50% posts, 50% products
                "price_range": {"min": 0, "max": 1000},
                "category_preferences": {},
                "engagement_preference": "high",  # high/medium/low
                "freshness_preference": "recent",  # recent/trending/classic
            }

            # Calculate content ratio
            if recent_likes and recent_views:
                total_engagement = len(recent_likes) + len(recent_views)
                preferences["content_ratio"] = len(recent_likes) / total_engagement

            # Calculate price preferences
            if recent_views:
                prices = [view.product.price for view in recent_views if view.product]
                if prices:
                    preferences["price_range"] = {
                        "min": min(prices),
                        "max": max(prices),
                    }

            # Calculate category preferences
            category_engagement = {}
            for like in recent_likes:
                # Get post with categories loaded
                post = (
                    session.query(Post)
                    .options(
                        joinedload(Post.categories).joinedload(PostCategory.category)
                    )
                    .get(like.post_id)
                )
                if post and post.categories:
                    for post_category in post.categories:
                        category_id = post_category.category_id
                        category_engagement[category_id] = (
                            category_engagement.get(category_id, 0) + 1
                        )

            for view in recent_views:
                # Get product with categories loaded
                product = (
                    session.query(Product)
                    .options(
                        joinedload(Product.categories).joinedload(
                            ProductCategory.category
                        )
                    )
                    .get(view.product_id)
                )
                if product and product.categories:
                    for product_category in product.categories:
                        category_id = product_category.category_id
                        category_engagement[category_id] = (
                            category_engagement.get(category_id, 0) + 1
                        )

            preferences["category_preferences"] = category_engagement

            return preferences

    @staticmethod
    def _get_followed_content(user_id):
        """Get content from followed sellers with enhanced scoring"""
        with session_scope() as session:
            # Get followed seller IDs
            followed_seller_ids = [
                seller_id[0]
                for seller_id in session.query(Seller.id)
                .join(Follow, Follow.followee_id == Seller.user_id)
                .filter(
                    Follow.follower_id == user_id,
                    # Follow.is_active == True,
                )
                .all()
            ]

            if not followed_seller_ids:
                return []

            # Get recent posts from followed sellers
            posts = (
                session.query(Post)
                .options(
                    joinedload(Post.niche_posts).joinedload(NichePost.niche),
                )
                .filter(
                    Post.seller_id.in_(followed_seller_ids),
                    Post.status == PostStatus.ACTIVE,
                )
                .order_by(Post.created_at.desc())
                .limit(50)
                .all()
            )

            # Filter posts based on niche visibility
            posts = FeedService._filter_posts_by_niche_visibility(posts, user_id)

            # Get recent products from followed sellers
            products = (
                session.query(Product)
                .filter(
                    Product.seller_id.in_(followed_seller_ids),
                    Product.status == Product.Status.ACTIVE,
                )
                .order_by(Product.created_at.desc())
                .limit(50)
                .all()
            )

            # Score and format items
            feed_items = []

            for post in posts:
                score = FeedService._calculate_post_score(post, user_id)
                feed_items.append(
                    {
                        "id": post.id,
                        "type": "post",
                        "score": score,
                        "created_at": post.created_at,
                    }
                )

            for product in products:
                score = FeedService._calculate_product_score(product, user_id)
                feed_items.append(
                    {
                        "id": product.id,
                        "type": "product",
                        "score": score,
                        "created_at": product.created_at,
                    }
                )

            return feed_items

    @staticmethod
    def _get_trending_by_interests(user_id, interests):
        """Get trending content filtered by user interests"""
        if not interests:
            return FeedService._get_trending_content()

        # Get trending content from Redis
        try:
            trending_posts = redis_client.zrevrange(
                "popular_posts", 0, 99, withscores=True
            )
            trending_products = redis_client.zrevrange(
                "popular_products", 0, 99, withscores=True
            )
        except RedisError:
            return []

        # Filter by interests
        filtered_items = []

        # Process trending posts
        for post_id, score in trending_posts:
            if isinstance(post_id, bytes):
                post_id = post_id.decode("utf-8")

            # Check if post category matches user interests
            with session_scope() as session:
                post = (
                    session.query(Post)
                    .options(
                        joinedload(Post.categories).joinedload(PostCategory.category)
                    )
                    .filter(Post.id == post_id)
                    .first()
                )
                if post and post.categories:
                    # Check if any of the post's categories match user interests
                    post_category_ids = [pc.category_id for pc in post.categories]
                    if any(cat_id in interests for cat_id in post_category_ids):
                        filtered_items.append(
                            {
                                "id": post_id,
                                "type": "post",
                                "score": score,
                                "created_at": post.created_at,
                            }
                        )

        # Process trending products
        for product_id, score in trending_products:
            if isinstance(product_id, bytes):
                product_id = product_id.decode("utf-8")

            # Check if product category matches user interests
            with session_scope() as session:
                product = (
                    session.query(Product)
                    .options(
                        joinedload(Product.categories).joinedload(
                            ProductCategory.category
                        )
                    )
                    .filter(Product.id == product_id)
                    .first()
                )
                if product and product.categories:
                    # Check if any of the product's categories match user interests
                    product_category_ids = [pc.category_id for pc in product.categories]
                    if any(cat_id in interests for cat_id in product_category_ids):
                        filtered_items.append(
                            {
                                "id": product_id,
                                "type": "product",
                                "score": score,
                                "created_at": product.created_at,
                            }
                        )

        return filtered_items

    @staticmethod
    def _get_discover_content(user_id, preferences):
        """Get discovery content based on user preferences. All returned items must be dicts with 'id', 'type', 'score', and 'created_at'."""
        with session_scope() as session:
            discover_items = []

            # Get posts from categories user might like
            posts = []
            if preferences.get("category_preferences"):
                top_categories = sorted(
                    preferences["category_preferences"].items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:5]
                category_ids = [cat[0] for cat in top_categories]
                posts = (
                    session.query(Post)
                    .join(PostCategory)
                    .options(
                        joinedload(Post.niche_posts).joinedload(NichePost.niche),
                    )
                    .filter(
                        PostCategory.category_id.in_(category_ids),
                        Post.status == PostStatus.ACTIVE,
                    )
                    .order_by(Post.created_at.desc())
                    .limit(20)
                    .all()
                )
                posts = FeedService._filter_posts_by_niche_visibility(posts, user_id)

            for post in posts:
                score = (
                    FeedService._calculate_post_score(post, user_id)
                    if hasattr(FeedService, "_calculate_post_score")
                    else 1
                )
                discover_items.append(
                    {
                        "id": post.id,
                        "type": "post",
                        "score": score,
                        "created_at": post.created_at
                        if hasattr(post, "created_at")
                        else datetime.utcnow(),
                    }
                )

            # Get products in user's price range
            price_range = preferences.get("price_range", {"min": 0, "max": 1000})
            products = (
                session.query(Product)
                .filter(
                    Product.price.between(price_range["min"], price_range["max"]),
                    Product.status == Product.Status.ACTIVE,
                )
                .order_by(Product.created_at.desc())
                .limit(20)
                .all()
            )
            for product in products:
                score = (
                    FeedService._calculate_product_score(product, user_id)
                    if hasattr(FeedService, "_calculate_product_score")
                    else 1
                )
                discover_items.append(
                    {
                        "id": product.id,
                        "type": "product",
                        "score": score,
                        "created_at": product.created_at
                        if hasattr(product, "created_at")
                        else datetime.utcnow(),
                    }
                )

            return discover_items

    @staticmethod
    def _apply_personalization_scoring(items, user_id):
        """Apply personalized scoring to feed items. Handles missing 'created_at' gracefully."""
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "post":
                with session_scope() as session:
                    post = session.query(Post).filter(Post.id == item["id"]).first()
                    if post:
                        is_followed = FeedService._is_from_followed_seller(
                            post, user_id
                        )
                        if is_followed:
                            item["score"] *= 1.5
                        matches_interests = FeedService._matches_user_interests(
                            post, user_id
                        )
                        if matches_interests:
                            item["score"] *= 1.3
                        created_at = item.get("created_at") or getattr(
                            post, "created_at", datetime.utcnow()
                        )
                        time_decay = FeedService._calculate_time_decay(created_at)
                        item["score"] *= time_decay
            elif item.get("type") == "product":
                with session_scope() as session:
                    product = (
                        session.query(Product).filter(Product.id == item["id"]).first()
                    )
                    if product:
                        matches_preferences = FeedService._matches_user_preferences(
                            product, user_id
                        )
                        if matches_preferences:
                            item["score"] *= 1.4
                        created_at = item.get("created_at") or getattr(
                            product, "created_at", datetime.utcnow()
                        )
                        time_decay = FeedService._calculate_time_decay(created_at)
                        item["score"] *= time_decay
        return items

    @staticmethod
    def _calculate_time_decay(created_at):
        """Calculate time decay factor for content freshness"""
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

        age_hours = (datetime.utcnow() - created_at).total_seconds() / 3600

        # Exponential decay: newer content gets higher scores
        decay_factor = math.exp(-age_hours / 24)  # 24-hour half-life
        return max(0.1, decay_factor)  # Minimum 10% score

    @staticmethod
    def _apply_diversity_and_freshness(items):
        """Apply diversity and freshness to feed items"""
        if not items:
            return []

        # Sort by score
        items.sort(key=lambda x: x["score"], reverse=True)

        # Apply diversity: ensure mix of content types
        posts = [item for item in items if item["type"] == "post"]
        products = [item for item in items if item["type"] == "product"]

        # Interleave posts and products for diversity
        diverse_items = []
        max_items = min(len(posts), len(products))

        for i in range(max_items):
            if posts[i]["score"] > products[i]["score"]:
                diverse_items.append(posts[i])
                diverse_items.append(products[i])
            else:
                diverse_items.append(products[i])
                diverse_items.append(posts[i])

        # Add remaining items
        remaining_posts = posts[max_items:]
        remaining_products = products[max_items:]
        diverse_items.extend(remaining_posts)
        diverse_items.extend(remaining_products)

        return diverse_items[:100]  # Limit to 100 items

    @staticmethod
    def _get_fallback_feed(page=1, per_page=20):
        """Get fallback trending feed when personalized feed fails"""
        try:
            # Get trending content from Redis
            trending_posts = redis_client.zrevrange(
                "popular_posts", 0, 49, withscores=True
            )
            trending_products = redis_client.zrevrange(
                "popular_products", 0, 49, withscores=True
            )

            feed_items = []

            # Process trending posts
            for post_id, score in trending_posts:
                if isinstance(post_id, bytes):
                    post_id = post_id.decode("utf-8")
                feed_items.append(
                    {
                        "id": post_id,
                        "type": "post",
                        "score": score,
                    }
                )

            # Process trending products
            for product_id, score in trending_products:
                if isinstance(product_id, bytes):
                    product_id = product_id.decode("utf-8")
                feed_items.append(
                    {
                        "id": product_id,
                        "type": "product",
                        "score": score,
                    }
                )

            # If no trending content, get recent content from database
            if not feed_items:
                feed_items = FeedService._get_recent_content_fallback()

            # Hydrate and paginate
            hydrated_items = FeedService._hydrate_cached_items(feed_items)
            return FeedService._paginate_feed(hydrated_items, page, per_page)

        except Exception as e:
            logger.error(f"Fallback feed generation failed: {str(e)}")
            return {
                "items": [],
                "pagination": {"page": page, "per_page": per_page, "total": 0},
            }

    @staticmethod
    def _get_recent_content_fallback():
        """Get recent content from database as fallback"""
        try:
            with session_scope() as session:
                # Get recent posts
                recent_posts = (
                    session.query(Post)
                    .options(
                        joinedload(Post.niche_posts).joinedload(NichePost.niche),
                    )
                    .filter(Post.status == PostStatus.ACTIVE)
                    .order_by(Post.created_at.desc())
                    .limit(20)
                    .all()
                )

                # Filter posts based on niche visibility (for anonymous users, only public niches)
                recent_posts = FeedService._filter_posts_by_niche_visibility(
                    recent_posts, None
                )

                # Get recent products
                recent_products = (
                    session.query(Product)
                    .filter(Product.status == Product.Status.ACTIVE)
                    .order_by(Product.created_at.desc())
                    .limit(20)
                    .all()
                )

                feed_items = []

                # Add posts
                for post in recent_posts:
                    feed_items.append(
                        {
                            "id": post.id,
                            "type": "post",
                            "score": 10,  # Default score
                            "created_at": post.created_at,
                        }
                    )

                # Add products
                for product in recent_products:
                    feed_items.append(
                        {
                            "id": product.id,
                            "type": "product",
                            "score": 10,  # Default score
                            "created_at": product.created_at,
                        }
                    )

                return feed_items

        except Exception as e:
            logger.error(f"Recent content fallback failed: {str(e)}")
            return []

    @staticmethod
    def _cache_feed(user_id, feed_items, feed_type="personalized"):
        """Cache feed with user-specific key and metadata"""
        cache_key = FeedService.CACHE_KEYS["user_feed"].format(
            user_id=user_id, feed_type=feed_type
        )

        try:
            # Convert feed items to JSON-serializable format
            serializable_items = []
            for item in feed_items:
                # Debug logging for problematic items
                if not isinstance(item, dict):
                    logger.warning(
                        f"Non-dict item in feed_items: {type(item)} - {item}"
                    )
                    continue

                serializable_item = {
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "score": item.get("score", 0),
                    "created_at": item.get("created_at").isoformat()
                    if item.get("created_at")
                    else None,
                }
                serializable_items.append(serializable_item)

            # Cache feed items as JSON string
            import json

            redis_client.setex(cache_key, 1800, json.dumps(serializable_items))

            # Cache metadata
            metadata_key = FeedService.CACHE_KEYS["feed_metadata"].format(
                user_id=user_id
            )
            metadata = {
                "last_generated": datetime.utcnow().isoformat(),
                "feed_type": feed_type,
                "item_count": len(feed_items),
                "cache_duration": 1800,
            }
            redis_client.setex(metadata_key, 1800, json.dumps(metadata))

        except RedisError as e:
            logger.warning(f"Failed to cache feed for user {user_id}: {str(e)}")
        except Exception as e:
            logger.warning(f"Failed to serialize feed for user {user_id}: {str(e)}")
            logger.warning(f"Feed items type: {type(feed_items)}")
            if isinstance(feed_items, list):
                logger.warning(f"Feed items length: {len(feed_items)}")
                for i, item in enumerate(feed_items[:3]):  # Log first 3 items
                    logger.warning(f"Item {i} type: {type(item)}, value: {item}")

    @staticmethod
    def _paginate_feed(feed_items, page, per_page):
        """Paginate feed items with metadata"""
        if not feed_items:
            return {
                "items": [],
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": 0,
                    "pages": 0,
                    "has_next": False,
                    "has_prev": False,
                },
            }

        total = len(feed_items)
        start = (page - 1) * per_page
        end = start + per_page

        paginated_items = feed_items[start:end]

        return {
            "items": paginated_items,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
                "has_next": end < total,
                "has_prev": page > 1,
            },
        }

    @staticmethod
    def _is_from_followed_seller(post, user_id):
        """Check if post is from a followed seller"""
        with session_scope() as session:
            follow = (
                session.query(Follow)
                .filter(
                    Follow.follower_id == user_id,
                    Follow.followee_id == post.seller.user_id,
                    # Follow.is_active == True,
                )
                .first()
            )
            return follow is not None

    @staticmethod
    def _matches_user_interests(post, user_id):
        """Check if post matches user interests"""
        user_interests = FeedService._get_user_interests(user_id)
        if not post.categories:
            return False

        # Check if any of the post's categories match user interests
        post_category_ids = [pc.category_id for pc in post.categories]
        return any(cat_id in user_interests for cat_id in post_category_ids)

    @staticmethod
    def _matches_user_preferences(product, user_id):
        """Check if product matches user preferences"""
        user_preferences = FeedService._get_user_preferences(user_id)

        # Check price range
        price_range = user_preferences.get("price_range", {"min": 0, "max": 1000})
        if not (price_range["min"] <= product.price <= price_range["max"]):
            return False

        # Check category preferences
        category_preferences = user_preferences.get("category_preferences", {})
        if product.categories:
            product_category_ids = [pc.category_id for pc in product.categories]
            if any(cat_id in category_preferences for cat_id in product_category_ids):
                return True

        return False

    @staticmethod
    def _invalidate_user_feed_cache(user_id):
        """Invalidate user's feed cache when content changes"""
        try:
            # Get all feed cache keys for this user
            pattern = f"feed:user:{user_id}:*"
            keys = redis_client.keys(pattern)

            if keys:
                redis_client.delete(*keys)
                logger.info(
                    f"Invalidated {len(keys)} feed cache keys for user {user_id}"
                )

            # Also invalidate interest and preference caches
            interest_key = FeedService.CACHE_KEYS["user_interests"].format(
                user_id=user_id
            )
            preference_key = FeedService.CACHE_KEYS["user_preferences"].format(
                user_id=user_id
            )
            metadata_key = FeedService.CACHE_KEYS["feed_metadata"].format(
                user_id=user_id
            )

            redis_client.delete(interest_key, preference_key, metadata_key)

        except RedisError as e:
            logger.warning(
                f"Failed to invalidate feed cache for user {user_id}: {str(e)}"
            )

    @staticmethod
    def _get_trending_content():
        """Get trending content from Redis"""
        try:
            trending_posts = redis_client.zrevrange(
                "popular_posts", 0, 99, withscores=True
            )
            trending_products = redis_client.zrevrange(
                "popular_products", 0, 99, withscores=True
            )

            feed_items = []

            for post_id, score in trending_posts:
                if isinstance(post_id, bytes):
                    post_id = post_id.decode("utf-8")
                feed_items.append(
                    {
                        "id": post_id,
                        "type": "post",
                        "score": score,
                    }
                )

            for product_id, score in trending_products:
                if isinstance(product_id, bytes):
                    product_id = product_id.decode("utf-8")
                feed_items.append(
                    {
                        "id": product_id,
                        "type": "product",
                        "score": score,
                    }
                )

            return feed_items

        except RedisError as e:
            logger.warning(f"Failed to get trending content: {str(e)}")
            return []

    @staticmethod
    def _get_niche_content(niche_id, user_id):
        """Get content from specific niche"""
        with session_scope() as session:
            # Check if user has access to niche
            membership = (
                session.query(NicheMembership)
                .filter(
                    NicheMembership.niche_id == niche_id,
                    NicheMembership.user_id == user_id,
                    NicheMembership.is_active == True,
                )
                .first()
            )

            if not membership:
                return []

            # Get niche posts
            niche_posts = (
                session.query(NichePost)
                .filter(
                    NichePost.niche_id == niche_id,
                    NichePost.is_approved == True,
                )
                .order_by(NichePost.created_at.desc())
                .limit(50)
                .all()
            )

            feed_items = []
            for niche_post in niche_posts:
                score = FeedService._calculate_post_score(niche_post.post, user_id)
                feed_items.append(
                    {
                        "id": niche_post.post.id,
                        "type": "post",
                        "score": score,
                        "created_at": niche_post.post.created_at,
                    }
                )

            return feed_items

    @staticmethod
    def _calculate_post_score(post, user_id):
        """Calculate composite score for a post"""
        score = 0

        # 1. Base score for followed accounts
        is_followed = FeedService._is_from_followed_seller(post, user_id)
        score += 15 if is_followed else 5

        # 2. Engagement signals with logarithmic scaling
        score += math.log1p(len(post.likes)) * 2
        score += math.log1p(len(post.comments)) * 1.5

        # 3. Recency decay (halflife of 3 days)
        hours_old = (datetime.utcnow() - post.created_at).total_seconds() / 3600
        score *= 0.5 ** (hours_old / 72)

        # 4. Personalization bonus
        if FeedService._matches_user_interests(post, user_id):
            score *= 1.5

        return score

    @staticmethod
    def _calculate_product_score(product, user_id):
        """Calculate composite score for a product"""
        score = 0

        # 1. Base score
        score += 10

        # 2. Engagement signals
        score += math.log1p(product.view_count or 0) * 1.2
        score += math.log1p(len(product.reviews)) * 1.5

        # 3. Rating quality
        if product.average_rating and product.average_rating >= 4:
            score += 10
        elif product.average_rating and product.average_rating >= 3:
            score += 5

        # 4. Seller reputation
        if product.seller.verification_status == SellerVerificationStatus.VERIFIED:
            score += 5

        # 5. Personalization
        if FeedService._matches_user_preferences(product, user_id):
            score *= 1.5

        return score

    @staticmethod
    def _get_engaged_seller_content(user_id):
        """Get content from sellers the user has previously engaged with (liked posts)"""
        with session_scope() as session:
            # Get sellers whose posts the user has liked
            engaged_seller_ids = (
                session.query(Post.seller_id)
                .join(PostLike, Post.id == PostLike.post_id)
                .filter(PostLike.user_id == user_id)
                .distinct()
                .all()
            )

            engaged_seller_ids = [seller_id[0] for seller_id in engaged_seller_ids]

            if not engaged_seller_ids:
                return []

            # Get recent posts from engaged sellers
            posts = (
                session.query(Post)
                .options(
                    joinedload(Post.niche_posts).joinedload(NichePost.niche),
                )
                .filter(
                    Post.seller_id.in_(engaged_seller_ids),
                    Post.status == PostStatus.ACTIVE,
                )
                .order_by(Post.created_at.desc())
                .limit(30)
                .all()
            )

            # Filter posts based on niche visibility
            posts = FeedService._filter_posts_by_niche_visibility(posts, user_id)

            # Get recent products from engaged sellers
            products = (
                session.query(Product)
                .filter(
                    Product.seller_id.in_(engaged_seller_ids),
                    Product.status == Product.Status.ACTIVE,
                )
                .order_by(Product.created_at.desc())
                .limit(30)
                .all()
            )

            # Score and format items with higher weight for engagement
            feed_items = []

            for post in posts:
                score = FeedService._calculate_post_score(post, user_id)
                # Boost score for posts from engaged sellers
                score *= 1.3
                feed_items.append(
                    {
                        "id": post.id,
                        "type": "post",
                        "score": score,
                        "created_at": post.created_at,
                    }
                )

            for product in products:
                score = FeedService._calculate_product_score(product, user_id)
                # Boost score for products from engaged sellers
                score *= 1.2
                feed_items.append(
                    {
                        "id": product.id,
                        "type": "product",
                        "score": score,
                        "created_at": product.created_at,
                    }
                )

            return feed_items

    @staticmethod
    def _can_user_see_niche_post(post, user_id):
        """Check if user can see a niche post based on visibility and membership"""
        if not post.niche_posts:
            return True  # Not a niche post, always visible

        niche_post = post.niche_posts[0]  # Assuming one niche per post
        niche = niche_post.niche

        # Public niches are always visible
        if niche.visibility == NicheVisibility.PUBLIC:
            return True

        # Private and restricted niches require membership
        if not user_id:
            return False

        with session_scope() as session:
            membership = (
                session.query(NicheMembership)
                .filter(
                    NicheMembership.niche_id == niche.id,
                    NicheMembership.user_id == user_id,
                    NicheMembership.is_active == True,
                )
                .first()
            )
            return membership is not None

    @staticmethod
    def _filter_posts_by_niche_visibility(posts, user_id):
        """Filter posts based on niche visibility and user membership"""
        filtered_posts = []
        for post in posts:
            if FeedService._can_user_see_niche_post(post, user_id):
                filtered_posts.append(post)
        return filtered_posts


class ReactionService:
    """Service for managing reactions on comments"""

    @staticmethod
    def add_comment_reaction(user_id: str, comment_id: int, reaction_type: str):
        """Add or update a reaction on a comment"""
        with session_scope() as session:
            # Check if comment exists
            comment = session.query(PostComment).get(comment_id)
            if not comment:
                raise NotFoundError("Comment not found")

            # Check if user already has this reaction
            existing_reaction = (
                session.query(PostCommentReaction)
                .filter_by(
                    comment_id=comment_id, user_id=user_id, reaction_type=reaction_type
                )
                .first()
            )

            if existing_reaction:
                # User already has this reaction, return existing
                return existing_reaction

            # Create new reaction
            reaction = PostCommentReaction(
                comment_id=comment_id, user_id=user_id, reaction_type=reaction_type
            )
            session.add(reaction)
            session.commit()

            # Queue async real-time event (non-blocking)
            try:
                from app.realtime.event_manager import EventManager

                user = session.query(User).get(user_id)
                EventManager.emit_to_comment(
                    comment_id,
                    "comment_reaction_added",
                    {
                        "comment_id": comment_id,
                        "user_id": user_id,
                        "username": user.username if user else "Unknown",
                        "reaction_type": reaction_type,
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to queue comment_reaction_added event: {e}")

            return reaction

    @staticmethod
    def remove_comment_reaction(user_id: str, comment_id: int, reaction_type: str):
        """Remove a reaction from a comment"""
        with session_scope() as session:
            reaction = (
                session.query(PostCommentReaction)
                .filter_by(
                    comment_id=comment_id, user_id=user_id, reaction_type=reaction_type
                )
                .first()
            )

            if not reaction:
                raise NotFoundError("Reaction not found")

            session.delete(reaction)
            session.commit()

            # Queue async real-time event (non-blocking)
            try:
                from app.realtime.event_manager import EventManager
                from app.users.models import User

                user = session.query(User).get(user_id)
                EventManager.emit_to_comment(
                    comment_id,
                    "comment_reaction_removed",
                    {
                        "comment_id": comment_id,
                        "user_id": user_id,
                        "username": user.username if user else "Unknown",
                        "reaction_type": reaction_type,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to queue comment_reaction_removed event: {e}")

            return True

    @staticmethod
    def get_comment_reactions(comment_id: int, user_id: str = None):
        """Get all reactions for a comment with counts and user's reactions"""
        with session_scope() as session:
            # Get all reactions for the comment
            reactions = (
                session.query(PostCommentReaction)
                .filter_by(comment_id=comment_id)
                .all()
            )

            # Group by reaction type and count
            reaction_counts = {}
            user_reactions = set()

            for reaction in reactions:
                reaction_type = reaction.reaction_type.value
                reaction_counts[reaction_type] = (
                    reaction_counts.get(reaction_type, 0) + 1
                )

                if user_id and reaction.user_id == user_id:
                    user_reactions.add(reaction_type)

            # Format response
            result = []
            for reaction_type, count in reaction_counts.items():
                result.append(
                    {
                        "reaction_type": reaction_type,
                        "count": count,
                        "has_reacted": reaction_type in user_reactions,
                    }
                )

            return result


class TrendingService:
    @staticmethod
    def get_trending_content(user_id=None, page=1, per_page=20):
        """Get trending content personalized for user with pagination"""
        try:
            trending = []

            # Calculate offset for pagination
            offset = (page - 1) * per_page
            end_index = offset + per_page - 1

            # Get globally popular posts with pagination
            post_ids = redis_client.zrevrange("popular_posts", offset, end_index)
            if post_ids:
                with session_scope() as session:
                    posts = (
                        session.query(Post)
                        .filter(Post.id.in_(post_ids))
                        .options(
                            joinedload(Post.seller).joinedload(Seller.user),
                            joinedload(Post.social_media),
                            joinedload(Post.tagged_products).joinedload(
                                PostProduct.product
                            ),
                            joinedload(Post.likes),
                            joinedload(Post.comments),
                        )
                        .all()
                    )

                    trending.extend(
                        [
                            {
                                "type": "post",
                                "data": p,
                                "score": redis_client.zscore("popular_posts", p.id)
                                or 0,
                                "created_at": p.created_at,
                            }
                            for p in posts
                        ]
                    )

            # Get total count for pagination
            total_items = redis_client.zcard("popular_posts")
            total_pages = (total_items + per_page - 1) // per_page if total_items else 0

            return {
                "items": trending,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_items": total_items,
                    "total_pages": total_pages,
                },
            }

        except Exception as e:
            logger.error(f"Trending content error: {str(e)}")
            return {
                "items": [],
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_items": 0,
                    "total_pages": 0,
                },
            }
