import logging
from datetime import datetime
from flask_socketio import Namespace, emit, join_room, leave_room
from flask_login import current_user
from external.redis import redis_client

logger = logging.getLogger(__name__)


class SocialNamespace(Namespace):
    def on_connect(self):
        """Handle client connection for social features"""
        if not current_user.is_authenticated:
            logger.warning("Unauthorized social connection attempt")
            return emit("error", {"message": "Unauthorized"})

        # Join user-specific room
        join_room(f"user_{current_user.id}")

        # Mark user as online
        redis_client.set(f"user_online:{current_user.id}", "1", ex=300)
        emit("connected", {"status": "connected"})
        logger.info(f"User {current_user.id} connected")

    def on_disconnect(self):
        """Handle client disconnection"""
        if current_user.is_authenticated:
            leave_room(f"user_{current_user.id}")
            redis_client.delete(f"user_online:{current_user.id}")
            logger.info(f"User {current_user.id} disconnected")

    # ==================== TYPING INDICATORS ====================
    def on_typing_start(self, data):
        """Handle typing indicators for posts"""
        if not current_user.is_authenticated:
            return

        post_id = data.get("post_id")
        if not post_id:
            return emit("error", {"message": "Missing post_id"})

        # Track typing status
        redis_client.hset(
            f"typing:post:{post_id}", current_user.id, datetime.utcnow().isoformat()
        )
        redis_client.expire(f"typing:post:{post_id}", 10)

        emit(
            "typing_update",
            {
                "post_id": post_id,
                "user_id": current_user.id,
                "username": current_user.username,
                "action": "start",
            },
            room=f"post_{post_id}",
            include_self=False,
        )

    def on_typing_stop(self, data):
        """Handle typing stop"""
        if not current_user.is_authenticated:
            return

        post_id = data.get("post_id")
        if post_id:
            redis_client.hdel(f"typing:post:{post_id}", current_user.id)
            emit(
                "typing_update",
                {"post_id": post_id, "user_id": current_user.id, "action": "stop"},
                room=f"post_{post_id}",
                include_self=False,
            )

    # ==================== POST ENGAGEMENT ====================
    def on_join_post(self, post_id):
        """Join room for post updates"""
        if current_user.is_authenticated:
            join_room(f"post_{post_id}")
            emit(
                "post_stats",
                {
                    "post_id": post_id,
                    "like_count": redis_client.zcard(f"post:{post_id}:likes"),
                    "comment_count": redis_client.get(f"post:{post_id}:comments") or 0,
                },
            )

    def on_leave_post(self, post_id):
        """Leave post room"""
        if current_user.is_authenticated:
            leave_room(f"post_{post_id}")

    # ==================== PRODUCT ENGAGEMENT ====================
    def on_join_product(self, product_id):
        """Join room for product updates"""
        if current_user.is_authenticated:
            join_room(f"product_{product_id}")
            stats = redis_client.hgetall(f"product:{product_id}:stats")
            emit(
                "product_stats",
                {
                    "product_id": product_id,
                    "view_count": int(stats.get(b"view_count", 0)),
                    "review_count": int(stats.get(b"review_count", 0)),
                    "avg_rating": float(stats.get(b"avg_rating", 0)),
                },
            )

    def on_leave_product(self, product_id):
        """Leave product room"""
        if current_user.is_authenticated:
            leave_room(f"product_{product_id}")

    # ==================== FOLLOW UPDATES ====================
    def on_follow(self, user_id):
        """Handle follow updates"""
        if current_user.is_authenticated and user_id != current_user.id:
            # Broadcast updates
            emit(
                "follower_update",
                {
                    "user_id": user_id,
                    "follower_count": redis_client.scard(f"user:{user_id}:followers"),
                },
                room=f"user_{user_id}",
            )

            emit(
                "following_update",
                {
                    "user_id": current_user.id,
                    "following_count": redis_client.scard(
                        f"user:{current_user.id}:following"
                    ),
                },
            )

    # ==================== UTILITY ====================
    def on_ping(self, data):
        """Keep connection alive"""
        if current_user.is_authenticated:
            redis_client.set(f"user_online:{current_user.id}", "1", ex=300)
            emit("pong", {"timestamp": datetime.utcnow().isoformat()})
