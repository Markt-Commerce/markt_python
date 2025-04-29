import redis
from redis.commands.json.path import Path
from main.config import settings
import logging

logger = logging.getLogger(__name__)


class RedisClient:
    def __init__(self):
        self.client = redis.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True
        )
        logger.info("Redis client initialized")

    def store_recovery_code(self, email: str, code: str, expires_in: int = 600):
        key = f"recovery:{email}"
        self.client.setex(key, expires_in, code)

    def verify_recovery_code(self, email: str, code: str) -> bool:
        stored = self.client.get(f"recovery:{email}")
        return stored and stored == code

    def delete_recovery_code(self, email: str):
        self.client.delete(f"recovery:{email}")

    # Product views counter
    def increment_product_views(self, product_id):
        self.client.zincrby("product_views", 1, product_id)

    # Real-time notifications
    def push_notification(self, user_id, message):
        self.client.lpush(f"notifications:{user_id}", message)

    # Shopping cart cache
    def cache_cart(self, user_id, cart_data):
        self.client.setex(f"cart:{user_id}", 3600, cart_data)


redis_client = RedisClient()
