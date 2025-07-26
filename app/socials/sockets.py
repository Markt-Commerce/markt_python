import logging
from datetime import datetime
from flask_socketio import Namespace, emit, join_room, leave_room
from flask_login import current_user
from external.redis import redis_client

logger = logging.getLogger(__name__)


class SocialNamespace(Namespace):
    """Enhanced social namespace with rate limiting and validation"""

    # Rate limiting configuration
    RATE_LIMITS = {
        "typing_start": {"max_calls": 10, "window": 60},  # 10 calls per minute
        "typing_stop": {"max_calls": 10, "window": 60},
        "follow": {"max_calls": 5, "window": 60},  # 5 follows per minute
        "ping": {"max_calls": 30, "window": 60},  # 30 pings per minute
    }

    def _check_rate_limit(self, event_type: str, user_id: str) -> bool:
        """Check if user has exceeded rate limit for event type"""
        try:
            key = f"rate_limit:{event_type}:{user_id}"
            current = redis_client.get(key)

            if current and int(current) >= self.RATE_LIMITS[event_type]["max_calls"]:
                return False

            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, self.RATE_LIMITS[event_type]["window"])
            pipe.execute()

            return True
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            return True  # Allow if rate limiting fails

    def _validate_data(self, data: dict, required_fields: list) -> tuple[bool, str]:
        """Validate incoming data"""
        if not data:
            return False, "No data provided"

        for field in required_fields:
            if field not in data:
                return False, f"Missing required field: {field}"

        return True, ""

    def on_connect(self):
        """Handle client connection for social features"""
        from main.sockets import SocketManager

        try:
            if not current_user.is_authenticated:
                logger.warning("Unauthorized social connection attempt")
                return emit("error", {"message": "Unauthorized"})

            # Join user-specific room
            join_room(f"user_{current_user.id}")

            # Mark user as online using centralized manager
            SocketManager.mark_user_online(current_user.id, "social")

            emit("connected", {"status": "connected", "user_id": current_user.id})
            logger.info(f"User {current_user.id} connected to social namespace")

        except Exception as e:
            logger.error(f"Social connection error: {e}")
            emit("error", {"message": "Connection failed"})

    def on_disconnect(self):
        """Handle client disconnection"""
        from main.sockets import SocketManager

        try:
            if current_user.is_authenticated:
                leave_room(f"user_{current_user.id}")
                SocketManager.mark_user_offline(current_user.id)
                logger.info(
                    f"User {current_user.id} disconnected from social namespace"
                )
        except Exception as e:
            logger.error(f"Social disconnection error: {e}")

    # ==================== TYPING INDICATORS ====================
    def on_typing_start(self, data):
        """Handle typing indicators for posts with validation"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("typing_start", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["post_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            post_id = data.get("post_id")

            # Validate post exists
            from app.socials.services import PostService

            if not PostService.post_exists(post_id):
                return emit("error", {"message": "Post not found"})

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
                    "timestamp": datetime.utcnow().isoformat(),
                },
                room=f"post_{post_id}",
                include_self=False,
            )

        except Exception as e:
            logger.error(f"Typing start error: {e}")
            emit("error", {"message": "Failed to process typing start"})

    def on_typing_stop(self, data):
        """Handle typing stop with validation"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("typing_stop", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["post_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            post_id = data.get("post_id")
            redis_client.hdel(f"typing:post:{post_id}", current_user.id)

            emit(
                "typing_update",
                {
                    "post_id": post_id,
                    "user_id": current_user.id,
                    "action": "stop",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                room=f"post_{post_id}",
                include_self=False,
            )

        except Exception as e:
            logger.error(f"Typing stop error: {e}")
            emit("error", {"message": "Failed to process typing stop"})

    # ==================== POST ENGAGEMENT ====================
    def on_join_post(self, post_id):
        """Join room for post updates with validation"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            if not post_id:
                return emit("error", {"message": "Post ID required"})

            # Validate post exists
            from app.socials.services import PostService

            if not PostService.post_exists(post_id):
                return emit("error", {"message": "Post not found"})

            join_room(f"post_{post_id}")

            # Get real-time stats
            like_count = redis_client.zcard(f"post:{post_id}:likes")
            comment_count = redis_client.get(f"post:{post_id}:comments") or 0

            emit(
                "post_stats",
                {
                    "post_id": post_id,
                    "like_count": like_count,
                    "comment_count": int(comment_count),
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Join post error: {e}")
            emit("error", {"message": "Failed to join post"})

    def on_leave_post(self, post_id):
        """Leave post room"""
        try:
            if current_user.is_authenticated and post_id:
                leave_room(f"post_{post_id}")
        except Exception as e:
            logger.error(f"Leave post error: {e}")

    # ==================== PRODUCT ENGAGEMENT ====================
    def on_join_product(self, product_id):
        """Join room for product updates with validation"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            if not product_id:
                return emit("error", {"message": "Product ID required"})

            # Validate product exists
            from app.products.services import ProductService

            if not ProductService.product_exists(product_id):
                return emit("error", {"message": "Product not found"})

            join_room(f"product_{product_id}")

            # Get real-time stats
            stats = redis_client.hgetall(f"product:{product_id}:stats")
            emit(
                "product_stats",
                {
                    "product_id": product_id,
                    "view_count": int(stats.get(b"view_count", 0)),
                    "review_count": int(stats.get(b"review_count", 0)),
                    "avg_rating": float(stats.get(b"avg_rating", 0)),
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Join product error: {e}")
            emit("error", {"message": "Failed to join product"})

    def on_leave_product(self, product_id):
        """Leave product room"""
        try:
            if current_user.is_authenticated and product_id:
                leave_room(f"product_{product_id}")
        except Exception as e:
            logger.error(f"Leave product error: {e}")

    # ==================== FOLLOW UPDATES ====================
    def on_follow(self, data):
        """Handle follow updates with validation and rate limiting"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("follow", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["user_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            user_id = data.get("user_id")

            if user_id == current_user.id:
                return emit("error", {"message": "Cannot follow yourself"})

            # Validate target user exists
            from app.users.services import UserService

            if not UserService.user_exists(user_id):
                return emit("error", {"message": "User not found"})

            # Broadcast updates
            emit(
                "follower_update",
                {
                    "user_id": user_id,
                    "follower_count": redis_client.scard(f"user:{user_id}:followers"),
                    "timestamp": datetime.utcnow().isoformat(),
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
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Follow error: {e}")
            emit("error", {"message": "Failed to process follow"})

    # ==================== UTILITY ====================
    def on_ping(self, data):
        """Keep connection alive with rate limiting"""
        from main.sockets import SocketManager

        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("ping", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Refresh online status
            SocketManager.mark_user_online(current_user.id, "social")
            emit("pong", {"timestamp": datetime.utcnow().isoformat()})

        except Exception as e:
            logger.error(f"Ping error: {e}")
            emit("error", {"message": "Ping failed"})
