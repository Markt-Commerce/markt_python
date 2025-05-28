import logging
from datetime import datetime, timedelta

from main.tasks import celery_app

from external.redis import redis_client
from external.database import db
from app.users.models import User
from app.products.services import ProductService

from .models import Post
from .services import FeedService

logger = logging.getLogger(__name__)


@celery_app.task
def generate_all_feeds():
    """Full feed regeneration for all users"""
    try:
        with db.session_scope() as session:
            users = session.query(User.id).filter(User.is_active == True).all()
            for (user_id,) in users:
                generate_user_feed(user_id)
    except Exception as e:
        logger.error(f"Full feed generation failed: {str(e)}")
        raise


def generate_user_feed(user_id):
    """Generate and cache feed for single user"""
    try:
        feed_items = FeedService._generate_fresh_feed(user_id)
        FeedService._cache_feed(user_id, feed_items)
        logger.info(f"Generated feed for user {user_id}")
    except Exception as e:
        logger.error(f"Failed generating feed for user {user_id}: {str(e)}")
        raise


@celery_app.task
def update_popular_content():
    """Update trending content metrics"""
    try:
        # Update popular posts
        with db.session_scope() as session:
            posts = (
                session.query(Post)
                .filter(Post.created_at >= datetime.utcnow() - timedelta(days=7))
                .order_by(db.func.array_length(Post.likes, 1).desc())
                .limit(50)
                .all()
            )

            with redis_client.pipeline() as pipe:
                pipe.delete("popular_posts")
                for post in posts:
                    pipe.zadd("popular_posts", {post.id: len(post.likes)})
                pipe.execute()

        # Update trending products
        ProductService.update_trending_products()

    except Exception as e:
        logger.error(f"Trending update failed: {str(e)}")
        raise
