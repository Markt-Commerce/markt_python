from datetime import datetime, timedelta
from external.redis import redis_client
from external.database import db
from app.users.models import User
from .models import Post
from .services import FeedService


def update_popular_posts():
    """Update Redis cache with popular posts"""
    with db.session_scope() as session:
        # Get posts with most likes in last 7 days
        popular_posts = (
            session.query(Post)
            .filter(Post.created_at >= datetime.utcnow() - timedelta(days=7))
            .order_by(db.func.array_length(Post.likes, 1).desc())
            .limit(50)
            .all()
        )

        # Update Redis sorted set
        for post in popular_posts:
            redis_client.zadd("popular_posts", {post.id: len(post.likes)})


def update_user_feeds():
    """Periodically update all user feeds"""
    # This would be more sophisticated in production
    with db.session_scope() as session:
        users = session.query(User).all()
        for user in users:
            FeedService._generate_feed_from_db(user.id)
