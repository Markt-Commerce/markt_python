import logging
import math
from datetime import datetime

# package imports
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

# project imports
from external.database import db
from external.redis import redis_client

from app.libs.session import session_scope
from app.libs.pagination import Paginator
from app.libs.errors import NotFoundError, ValidationError, ConflictError

from app.users.models import User, Seller
from app.products.models import Product, ProductStatus
from app.products.services import ProductService
from app.notifications.models import NotificationType
from app.notifications.services import NotificationService

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
)
from .constants import POST_STATUS_TRANSITIONS

logger = logging.getLogger(__name__)


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
        """Calculate composite score for a product"""
        score = 0

        # 1. Base score
        score += 10

        # 2. Popularity signals
        score += math.log1p(product.view_count) * 1.2
        score += math.log1p(product.like_count) * 1.5

        # 3. Commerce signals
        if product.seller.verification_status == "verified":
            score += 5

        # 4. Personalization
        if FeedService._matches_user_preferences(product, user_id):
            score *= 2

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
