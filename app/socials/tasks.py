# python imports
import logging
from datetime import datetime, timedelta
import json

# project imports
from main.workers import celery_app

from external.redis import redis_client
from external.database import db
from app.libs.session import session_scope

from app.users.models import User
from app.products.services import ProductService
from app.categories.models import Category, PostCategory, ProductCategory

# app imports
from .models import Post, ProductView, PostLike
from .services import FeedService

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def generate_all_feeds(self):
    """Full feed regeneration for all users with personalization"""
    try:
        with session_scope() as session:
            users = session.query(User.id).filter(User.is_active == True).all()
            for (user_id,) in users:
                # Generate different feed types for each user
                for feed_type in ["personalized", "trending", "following"]:
                    generate_user_feed.delay(user_id, feed_type)

        logger.info(f"Generated feeds for {len(users)} users")
    except Exception as e:
        logger.error(f"Full feed generation failed: {str(e)}")
        raise


@celery_app.task(bind=True, max_retries=3)
def generate_user_feed(self, user_id, feed_type="personalized"):
    """Generate and cache personalized feed for single user"""
    try:
        # Generate fresh feed with personalization
        feed_items = FeedService._generate_fresh_feed(user_id, feed_type)

        # Cache the feed with user-specific key
        FeedService._cache_feed(user_id, feed_items, feed_type)

        # Update user activity metrics
        update_user_activity_metrics.delay(user_id)

        logger.info(
            f"Generated {feed_type} feed for user {user_id} with {len(feed_items)} items"
        )

    except Exception as e:
        logger.error(f"Failed generating {feed_type} feed for user {user_id}: {str(e)}")
        # Retry logic with exponential backoff
        if self.request.retries < self.max_retries:
            logger.info(
                f"Retrying {feed_type} feed generation for user {user_id} (attempt {self.request.retries + 1})"
            )
            raise self.retry(
                countdown=60 * (2**self.request.retries)
            )  # Exponential backoff
        raise


@celery_app.task(bind=True)
def update_user_activity_metrics(self, user_id):
    """Update user activity metrics for personalization"""
    try:
        with session_scope() as session:
            # Calculate user interests based on recent activity
            recent_likes = (
                session.query(PostLike)
                .filter(PostLike.user_id == user_id)
                .order_by(PostLike.created_at.desc())
                .limit(100)
                .all()
            )

            recent_views = (
                session.query(ProductView)
                .filter(ProductView.user_id == user_id)
                .order_by(ProductView.viewed_at.desc())
                .limit(100)
                .all()
            )

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

            # Cache user preferences
            cache_key = f"user:{user_id}:preferences"
            preferences = {
                "category_engagement": category_engagement,
                "last_updated": datetime.utcnow().isoformat(),
                "total_likes": len(recent_likes),
                "total_views": len(recent_views),
            }

            redis_client.setex(cache_key, 7200, json.dumps(preferences))  # 2 hours

        logger.info(f"Updated activity metrics for user {user_id}")

    except Exception as e:
        logger.error(f"Failed to update activity metrics for user {user_id}: {str(e)}")


@celery_app.task(bind=True)
def update_popular_content(self):
    """Update trending content metrics with enhanced scoring"""
    try:
        # Update popular posts with engagement scoring
        with session_scope() as session:
            posts = (
                session.query(Post)
                .filter(Post.created_at >= datetime.utcnow() - timedelta(days=7))
                .all()
            )

            with redis_client.pipeline() as pipe:
                pipe.delete("popular_posts")
                for post in posts:
                    # Enhanced scoring: likes + comments + time decay
                    score = len(post.likes) * 2 + len(post.comments) * 1.5

                    # Time decay factor
                    hours_old = (
                        datetime.utcnow() - post.created_at
                    ).total_seconds() / 3600
                    time_decay = 0.5 ** (hours_old / 72)  # 3-day half-life
                    score *= time_decay

                    pipe.zadd("popular_posts", {post.id: score})
                pipe.execute()

        # Update trending products with sales and engagement data
        ProductService.update_trending_products()

        # Update category-based trending
        update_category_trending.delay()

    except Exception as e:
        logger.error(f"Trending update failed: {str(e)}")
        raise


@celery_app.task(bind=True)
def update_category_trending(self):
    """Update trending content by category"""
    try:
        with session_scope() as session:
            # Get all categories with posts
            categories = session.query(Category).join(PostCategory).distinct().all()

            for category in categories:
                # Get trending posts for this category
                category_posts = (
                    session.query(Post)
                    .join(PostCategory)
                    .filter(
                        PostCategory.category_id == category.id,
                        Post.created_at >= datetime.utcnow() - timedelta(days=7),
                    )
                    .order_by(db.func.array_length(Post.likes, 1).desc())
                    .limit(20)
                    .all()
                )

                # Cache category trending
                cache_key = f"trending:category:{category.id}"
                trending_data = []

                for post in category_posts:
                    score = len(post.likes) * 2 + len(post.comments) * 1.5
                    trending_data.append(
                        {
                            "id": post.id,
                            "score": score,
                            "created_at": post.created_at.isoformat(),
                        }
                    )

                redis_client.setex(cache_key, 3600, json.dumps(trending_data))  # 1 hour

        logger.info("Updated category trending data")

    except Exception as e:
        logger.error(f"Category trending update failed: {str(e)}")


@celery_app.task(bind=True)
def invalidate_user_feeds(self, user_id, reason="content_update"):
    """Invalidate user's feed cache when content changes"""
    try:
        # Invalidate all feed types for this user
        feed_types = ["personalized", "trending", "following", "discover"]

        for feed_type in feed_types:
            cache_key = f"feed:user:{user_id}:{feed_type}"
            redis_client.delete(cache_key)

        # Also invalidate user preferences and interests
        redis_client.delete(f"user:{user_id}:interests")
        redis_client.delete(f"user:{user_id}:preferences")
        redis_client.delete(f"feed:metadata:{user_id}")

        logger.info(f"Invalidated feeds for user {user_id} due to {reason}")

    except Exception as e:
        logger.error(f"Failed to invalidate feeds for user {user_id}: {str(e)}")


@celery_app.task(bind=True)
def cleanup_old_feed_cache(self):
    """Clean up old cached feeds and activity data"""
    try:
        # Clean up old feed cache entries (older than 24 hours)
        cutoff_time = datetime.utcnow() - timedelta(hours=24)

        # Get all feed cache keys
        feed_keys = redis_client.keys("feed:*")
        cleaned_count = 0

        for key in feed_keys:
            # Check if cache is old (this is a simplified approach)
            # In production, you might want to store timestamps with cache entries
            if redis_client.ttl(key) == -1:  # No expiration set
                redis_client.delete(key)
                cleaned_count += 1

        logger.info(f"Cleaned up {cleaned_count} old feed cache entries")

        # Clean up old user activity data (older than 7 days)
        activity_keys = redis_client.keys("user:*:preferences")
        for key in activity_keys:
            try:
                data = redis_client.get(key)
                if data:
                    activity_data = json.loads(data)
                    last_updated = datetime.fromisoformat(
                        activity_data.get("last_updated", "1970-01-01")
                    )
                    if (datetime.utcnow() - last_updated).days > 7:
                        redis_client.delete(key)
            except (json.JSONDecodeError, ValueError):
                # Delete invalid data
                redis_client.delete(key)

        # Clean up old typing indicators (older than 10 minutes)
        typing_keys = redis_client.keys("typing:*")
        for key in typing_keys:
            if redis_client.ttl(key) == -1:
                redis_client.delete(key)

        # Clean up old online status (older than 5 minutes)
        online_keys = redis_client.keys("user_online:*")
        for key in online_keys:
            if redis_client.ttl(key) == -1:
                redis_client.delete(key)

    except Exception as e:
        logger.error(f"Feed cache cleanup failed: {str(e)}")
        raise


@celery_app.task(bind=True)
def generate_discovery_feeds(self):
    """Generate discovery feeds for users based on their interests"""
    try:
        with session_scope() as session:
            users = session.query(User.id).filter(User.is_active == True).all()

            for (user_id,) in users:
                try:
                    # Get user preferences
                    cache_key = f"user:{user_id}:preferences"
                    cached_prefs = redis_client.get(cache_key)

                    if cached_prefs:
                        preferences = json.loads(cached_prefs)

                        # Generate discovery feed based on preferences
                        discovery_items = FeedService._get_discover_content(
                            user_id, preferences
                        )

                        # Cache discovery feed
                        FeedService._cache_feed(user_id, discovery_items, "discover")

                        logger.info(f"Generated discovery feed for user {user_id}")

                except Exception as e:
                    logger.warning(
                        f"Failed to generate discovery feed for user {user_id}: {str(e)}"
                    )
                    continue

    except Exception as e:
        logger.error(f"Discovery feed generation failed: {str(e)}")
        raise


@celery_app.task(bind=True)
def update_feed_analytics(self):
    """Update feed analytics and performance metrics"""
    try:
        # Track feed performance metrics
        analytics = {
            "total_feeds_generated": 0,
            "cache_hit_rate": 0,
            "average_feed_size": 0,
            "popular_categories": {},
            "user_engagement": {},
        }

        # Get feed generation stats
        feed_keys = redis_client.keys("feed:user:*")
        analytics["total_feeds_generated"] = len(feed_keys)

        # Calculate cache hit rates

        # This would typically come from your application metrics
        # For now, we'll use a placeholder approach

        # Cache analytics for 1 hour
        redis_client.setex("feed:analytics", 3600, json.dumps(analytics))

        logger.info("Updated feed analytics")

    except Exception as e:
        logger.error(f"Feed analytics update failed: {str(e)}")
        raise
