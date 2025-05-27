import logging

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
from app.products.models import Product

# app imports
from .models import (
    Post,
    PostMedia,
    PostProduct,
    Follow,
    PostLike,
    PostComment,
    FollowType,
)

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

                post = Post(seller_id=seller_id, caption=post_data.get("caption"))
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

                return like
        except SQLAlchemyError as e:
            logger.error(f"Error liking post: {str(e)}")
            raise ConflictError("Failed to like post")


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

                return follow
        except SQLAlchemyError as e:
            logger.error(f"Error following user: {str(e)}")
            raise ConflictError("Failed to follow user")


class FeedService:
    @staticmethod
    def get_user_feed(user_id, page=1, per_page=20):
        try:
            # First try to get feed from Redis
            feed_items = redis_client.zrevrange(f"user:{user_id}:feed", 0, -1)

            if not feed_items:
                # Fallback to database query
                feed_items = FeedService._generate_feed_from_db(user_id)

            # Paginate results
            paginator = Paginator(feed_items, page=page, per_page=per_page)
            return paginator.paginate()

        except Exception as e:
            logger.error(f"Error getting feed for user {user_id}: {str(e)}")
            raise NotFoundError("Failed to get feed")

    @staticmethod
    def _generate_feed_from_db(user_id):
        """Generate feed from database when Redis cache is empty"""
        with session_scope() as session:
            # Get posts from followed sellers
            followed_sellers = (
                session.query(Follow.followee_id)
                .filter(
                    Follow.follower_id == user_id,
                    Follow.follow_type == FollowType.CUSTOMER,
                )
                .subquery()
            )

            posts = (
                session.query(Post)
                .filter(Post.user_id.in_(followed_sellers))
                .order_by(Post.created_at.desc())
                .limit(100)
                .all()
            )

            # Convert to feed items format
            feed_items = [
                {"type": "post", "data": post, "created_at": post.created_at}
                for post in posts
            ]

            # Cache in Redis
            for item in feed_items:
                redis_client.zadd(
                    f"user:{user_id}:feed",
                    {str(item["data"].id): int(item["created_at"].timestamp())},
                )

            return feed_items
