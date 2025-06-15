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

        # Join user-specific room for social updates
        user_room = f"social_user_{current_user.id}"
        join_room(user_room)

        # Mark user as online for social features
        redis_client.set(f"social_online:{current_user.id}", "1", ex=300)  # 5 min TTL

        emit("social_connected", {"status": "connected"})
        logger.info(f"User {current_user.id} connected to social features")

    def on_disconnect(self):
        """Handle client disconnection"""
        if current_user.is_authenticated:
            user_room = f"social_user_{current_user.id}"
            leave_room(user_room)

            # Remove online status
            redis_client.delete(f"social_online:{current_user.id}")

            logger.info(f"User {current_user.id} disconnected from social features")

    # ==================== TYPING INDICATORS ====================

    def on_typing_start(self, data):
        """Handle typing indicator start for comments"""
        if not current_user.is_authenticated:
            return emit("error", {"message": "Unauthorized"})

        content_type = data.get("content_type")  # 'post' or 'product'
        content_id = data.get("content_id")

        if not content_type or not content_id:
            return emit("error", {"message": "Missing content info"})

        # Store typing status in Redis with TTL
        typing_key = f"typing:{content_type}:{content_id}"
        redis_client.hset(typing_key, current_user.id, datetime.utcnow().isoformat())
        redis_client.expire(typing_key, 10)  # 10 second TTL

        # Broadcast to other users viewing this content
        emit(
            "typing_update",
            {
                "content_type": content_type,
                "content_id": content_id,
                "user_id": current_user.id,
                "username": current_user.username,
                "action": "start",
            },
            room=f"{content_type}_{content_id}",
            include_self=False,
        )

    def on_typing_stop(self, data):
        """Handle typing indicator stop"""
        if not current_user.is_authenticated:
            return

        content_type = data.get("content_type")
        content_id = data.get("content_id")

        if not content_type or not content_id:
            return

        # Remove typing status
        typing_key = f"typing:{content_type}:{content_id}"
        redis_client.hdel(typing_key, current_user.id)

        # Broadcast stop
        emit(
            "typing_update",
            {
                "content_type": content_type,
                "content_id": content_id,
                "user_id": current_user.id,
                "action": "stop",
            },
            room=f"{content_type}_{content_id}",
            include_self=False,
        )

    # ==================== LIVE COUNT UPDATES ====================

    def on_join_content_room(self, data):
        """Join room for live updates on specific content"""
        if not current_user.is_authenticated:
            return

        content_type = data.get("content_type")  # 'post' or 'product'
        content_id = data.get("content_id")

        if not content_type or not content_id:
            return emit("error", {"message": "Missing content info"})

        content_room = f"{content_type}_{content_id}"
        join_room(content_room)

        # Send current counts
        like_count = redis_client.zcard(f"{content_type}:{content_id}:likes")
        comment_count = (
            redis_client.get(f"{content_type}:{content_id}:comment_count") or 0
        )

        emit(
            "content_stats",
            {
                "content_type": content_type,
                "content_id": content_id,
                "like_count": like_count,
                "comment_count": int(comment_count),
                "viewers": self._get_room_count(content_room),
            },
        )

    def on_leave_content_room(self, data):
        """Leave room for content updates"""
        if not current_user.is_authenticated:
            return

        content_type = data.get("content_type")
        content_id = data.get("content_id")

        if content_type and content_id:
            leave_room(f"{content_type}_{content_id}")

    # ==================== FOLLOW UPDATES ====================

    def on_follow_user(self, data):
        """Handle real-time follow updates (complement to notification)"""
        if not current_user.is_authenticated:
            return

        followed_user_id = data.get("user_id")
        if not followed_user_id:
            return

        # Update follower counts in real-time
        follower_count = redis_client.scard(f"user:{followed_user_id}:followers")
        following_count = redis_client.scard(f"user:{current_user.id}:following")

        # Notify followed user of new follower count
        emit(
            "follower_count_update",
            {"user_id": followed_user_id, "follower_count": follower_count},
            room=f"social_user_{followed_user_id}",
        )

        # Update current user's following count
        emit(
            "following_count_update",
            {"user_id": current_user.id, "following_count": following_count},
        )

    def on_unfollow_user(self, data):
        """Handle real-time unfollow updates"""
        if not current_user.is_authenticated:
            return

        unfollowed_user_id = data.get("user_id")
        if not unfollowed_user_id:
            return

        # Update counts
        follower_count = redis_client.scard(f"user:{unfollowed_user_id}:followers")
        following_count = redis_client.scard(f"user:{current_user.id}:following")

        # Notify unfollowed user
        emit(
            "follower_count_update",
            {"user_id": unfollowed_user_id, "follower_count": follower_count},
            room=f"social_user_{unfollowed_user_id}",
        )

        # Update current user
        emit(
            "following_count_update",
            {"user_id": current_user.id, "following_count": following_count},
        )

    # ==================== LIVE REACTION UPDATES ====================

    def on_content_liked(self, data):
        """Broadcast live like count updates"""
        if not current_user.is_authenticated:
            return

        content_type = data.get("content_type")
        content_id = data.get("content_id")

        if not content_type or not content_id:
            return

        # Get updated like count
        like_count = redis_client.zcard(f"{content_type}:{content_id}:likes")

        # Broadcast to all users viewing this content
        emit(
            "like_count_update",
            {
                "content_type": content_type,
                "content_id": content_id,
                "like_count": like_count,
                "liked_by": current_user.id,
            },
            room=f"{content_type}_{content_id}",
            include_self=False,
        )

    def on_content_unliked(self, data):
        """Broadcast live unlike count updates"""
        if not current_user.is_authenticated:
            return

        content_type = data.get("content_type")
        content_id = data.get("content_id")

        if not content_type or not content_id:
            return

        # Get updated like count
        like_count = redis_client.zcard(f"{content_type}:{content_id}:likes")

        # Broadcast to all users viewing this content
        emit(
            "like_count_update",
            {
                "content_type": content_type,
                "content_id": content_id,
                "like_count": like_count,
                "unliked_by": current_user.id,
            },
            room=f"{content_type}_{content_id}",
            include_self=False,
        )

    def on_comment_added(self, data):
        """Broadcast live comment count updates"""
        if not current_user.is_authenticated:
            return

        content_type = data.get("content_type")
        content_id = data.get("content_id")

        if not content_type or not content_id:
            return

        # Get updated comment count
        comment_count = (
            redis_client.get(f"{content_type}:{content_id}:comment_count") or 0
        )

        # Broadcast to all users viewing this content
        emit(
            "comment_count_update",
            {
                "content_type": content_type,
                "content_id": content_id,
                "comment_count": int(comment_count),
                "commented_by": current_user.id,
            },
            room=f"{content_type}_{content_id}",
            include_self=False,
        )

    # ==================== PRODUCT REVIEW UPDATES ====================

    def on_review_added(self, data):
        """Handle real-time review updates"""
        if not current_user.is_authenticated:
            return

        product_id = data.get("product_id")
        rating = data.get("rating")

        if not product_id or not rating:
            return

        # Get updated product stats
        avg_rating = redis_client.hget(f"product:{product_id}:stats", "avg_rating") or 0
        review_count = (
            redis_client.hget(f"product:{product_id}:stats", "review_count") or 0
        )

        # Broadcast to users viewing this product
        emit(
            "product_rating_update",
            {
                "product_id": product_id,
                "avg_rating": float(avg_rating),
                "review_count": int(review_count),
                "latest_rating": rating,
            },
            room=f"product_{product_id}",
        )

    # ==================== UTILITY METHODS ====================

    def on_ping(self, data):
        """Handle ping to keep social connection alive"""
        if current_user.is_authenticated:
            # Refresh online status
            redis_client.set(f"social_online:{current_user.id}", "1", ex=300)
            emit("pong", {"timestamp": data.get("timestamp")})

    def _get_room_count(self, room_name):
        """Get approximate count of users in a room"""
        try:
            # This is a simplified version - in production you might want
            # to track room membership more precisely
            return len(self.server.manager.get_participants(self.namespace, room_name))
        except:
            return 0
