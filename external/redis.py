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

    # Hash operations
    def hincrby(self, name, key, amount=1):
        """Wrapper for Redis hincrby command"""
        return self.client.hincrby(name, key, amount)

    def hget(self, name, key):
        """Wrapper for Redis hget command"""
        return self.client.hget(name, key)

    def hset(self, name, key=None, value=None, mapping=None):
        """Wrapper for Redis hset command"""
        return self.client.hset(name, key, value, mapping)

    def hgetall(self, name):
        """Wrapper for Redis hgetall command"""
        return self.client.hgetall(name)

    def hdel(self, name, *keys):
        """Wrapper for Redis hdel command"""
        return self.client.hdel(name, *keys)

    # Sorted set operations
    def zadd(self, name, mapping, nx=False, xx=False, ch=False, incr=False):
        """Wrapper for Redis zadd command"""
        return self.client.zadd(name, mapping, nx=nx, xx=xx, ch=ch, incr=incr)

    def zrem(self, name, *values):
        """Wrapper for Redis zrem command"""
        return self.client.zrem(name, *values)

    def zincrby(self, name, amount, value):
        """Wrapper for Redis zincrby command"""
        return self.client.zincrby(name, amount, value)

    def zrevrange(self, name, start, end, withscores=False):
        """Wrapper for Redis zrevrange command"""
        return self.client.zrevrange(name, start, end, withscores=withscores)

    def zscore(self, name, value):
        """Wrapper for Redis zscore command"""
        return self.client.zscore(name, value)

    def zcard(self, name):
        """Wrapper for Redis zcard command"""
        return self.client.zcard(name)

    def zrange(
        self, name, start, end, withscores=False, desc=False, score_cast_func=float
    ):
        """Wrapper for Redis zrange command with optional score processing"""
        return self.client.zrange(
            name,
            start,
            end,
            withscores=withscores,
            desc=desc,
            score_cast_func=score_cast_func,
        )

    def zrangebyscore(
        self,
        name,
        min_score,
        max_score,
        withscores=False,
        score_cast_func=float,
        offset=None,
        count=None,
    ):
        """Wrapper for Redis zrangebyscore command"""
        return self.client.zrangebyscore(
            name,
            min_score,
            max_score,
            withscores=withscores,
            score_cast_func=score_cast_func,
            start=offset,
            num=count,
        )

    def zrevrangebyscore(
        self,
        name,
        max_score,
        min_score,
        withscores=False,
        score_cast_func=float,
        offset=None,
        count=None,
    ):
        """Wrapper for Redis zrevrangebyscore command (reverse order)"""
        return self.client.zrevrangebyscore(
            name,
            max_score,
            min_score,
            withscores=withscores,
            score_cast_func=score_cast_func,
            start=offset,
            num=count,
        )

    def zpopmax(self, name, count=1):
        """Wrapper for Redis zpopmax command"""
        return self.client.zpopmax(name, count)

    def zpopmin(self, name, count=1):
        """Wrapper for Redis zpopmin command"""
        return self.client.zpopmin(name, count)

    # Basic operations you might also need
    def get(self, name):
        """Wrapper for Redis get command"""
        return self.client.get(name)

    def set(self, name, value, ex=None, px=None, nx=False, xx=False):
        """Wrapper for Redis set command"""
        return self.client.set(name, value, ex=ex, px=px, nx=nx, xx=xx)

    def setex(self, name, time, value):
        """Wrapper for Redis setex command"""
        return self.client.setex(name, time, value)

    def delete(self, *names):
        """Wrapper for Redis delete command"""
        return self.client.delete(*names)

    def exists(self, *names):
        """Wrapper for Redis exists command"""
        return self.client.exists(*names)

    def keys(self, pattern):
        """Wrapper for Redis keys command"""
        return self.client.keys(pattern)

    def ttl(self, name):
        """Wrapper for Redis ttl command"""
        return self.client.ttl(name)

    # Pub/Sub operations
    def publish(self, channel, message):
        """Wrapper for Redis publish command"""
        import json

        # Convert message to JSON if it's a dict/object
        if isinstance(message, (dict, list)):
            message = json.dumps(message)
        return self.client.publish(channel, message)

    def subscribe(self, *channels):
        """Wrapper for Redis subscribe - returns PubSub object"""
        pubsub = self.client.pubsub()
        pubsub.subscribe(*channels)
        return pubsub

    def psubscribe(self, *patterns):
        """Wrapper for Redis pattern subscribe - returns PubSub object"""
        pubsub = self.client.pubsub()
        pubsub.psubscribe(*patterns)
        return pubsub

    # Set operations
    def sadd(self, name, *values):
        """Wrapper for Redis sadd command"""
        return self.client.sadd(name, *values)

    def smembers(self, name):
        """Wrapper for Redis smembers command"""
        return self.client.smembers(name)

    def scard(self, name):
        """Wrapper for Redis scard command"""
        return self.client.scard(name)

    def srem(self, name, *values):
        """Wrapper for Redis srem command"""
        return self.client.srem(name, *values)

    # String operations
    def incr(self, name, amount=1):
        """Wrapper for Redis incr command"""
        return self.client.incr(name, amount)

    def decr(self, name, amount=1):
        """Wrapper for Redis decr command"""
        return self.client.decr(name, amount)

    def expire(self, name, time):
        """Wrapper for Redis expire command"""
        return self.client.expire(name, time)

    # Recovery code
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

    # Add pipeline support
    def pipeline(self):
        """Return Redis pipeline object"""
        return self.client.pipeline()

    # Ping operation
    def ping(self):
        """Wrapper for Redis ping command"""
        return self.client.ping()

    # Close connection
    def close(self):
        """Wrapper for Redis close command"""
        self.client.close()


redis_client = RedisClient()
