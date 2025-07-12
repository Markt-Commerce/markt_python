# python imports
import time
from typing import Optional, Callable, Any
from datetime import datetime

# package imports
from flask import request, abort, current_app, g
from flask_login import current_user, login_required
from functools import wraps

# project imports
from external.redis import redis_client
from .errors import ForbiddenError, ValidationError

logger = current_app.logger if current_app else None


def buyer_required(f):
    """Decorator to require buyer role"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401, message="Authentication required")

        if not current_user.is_buyer:
            raise ForbiddenError(message="Only buyers can access this endpoint")

        return f(*args, **kwargs)

    return decorated_function


def seller_required(f):
    """Decorator to require seller role"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401, message="Authentication required")

        if not current_user.is_seller:
            raise ForbiddenError(message="Only sellers can access this endpoint")

        if not current_user.seller_account or not current_user.seller_account.is_active:
            abort(403, message="Active seller account required")

        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """Decorator to require admin role"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401, message="Authentication required")

        # TODO: Implement proper admin check
        raise ForbiddenError(message="Admin access required")

        return f(*args, **kwargs)

    return decorated_function


def dual_role_required(f):
    """Decorator to require both buyer and seller roles"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401, message="Authentication required")

        if not current_user.is_buyer and not current_user.is_seller:
            abort(403, message="Buyer or seller account required")

        return f(*args, **kwargs)

    return decorated_function


def rate_limit(requests_per_minute: int = 60, key_func: Optional[Callable] = None):
    """Rate limiting decorator with Redis backend

    Args:
        requests_per_minute: Maximum requests allowed per minute
        key_func: Function to generate rate limit key (defaults to user ID or IP)
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Generate rate limit key
            if key_func:
                key = key_func()
            elif current_user.is_authenticated:
                key = f"rate_limit:user:{current_user.id}"
            else:
                key = f"rate_limit:ip:{request.remote_addr}"

            # Check rate limit
            current_time = int(time.time())
            window_start = current_time - 60  # 1 minute window

            try:
                # Get current request count
                pipe = redis_client.pipeline()
                pipe.zremrangebyscore(key, 0, window_start)  # Remove old entries
                pipe.zadd(key, {str(current_time): current_time})  # Add current request
                pipe.zcard(key)  # Get count
                pipe.expire(key, 60)  # Set expiry
                _, _, request_count, _ = pipe.execute()

                if request_count > requests_per_minute:
                    abort(
                        429,
                        message=f"Rate limit exceeded. Maximum {requests_per_minute} requests per minute.",
                    )

            except Exception as e:
                # If Redis fails, log but don't block the request
                if logger:
                    logger.warning(f"Rate limiting failed: {str(e)}")

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def validate_input(schema_class):
    """Input validation decorator using marshmallow schemas"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                # Validate request data
                schema = schema_class()
                if request.method in ["POST", "PUT", "PATCH"]:
                    data = request.get_json() or {}
                    validated_data = schema.load(data)
                    g.validated_data = validated_data
                elif request.method == "GET":
                    data = request.args.to_dict()
                    validated_data = schema.load(data)
                    g.validated_data = validated_data

                return f(*args, **kwargs)
            except Exception as e:
                abort(400, message=f"Invalid input: {str(e)}")

        return decorated_function

    return decorator


def sanitize_input(f):
    """Input sanitization decorator to prevent XSS and injection attacks"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Store original request data
        g.original_data = request.get_json() if request.is_json else {}

        # Basic sanitization (you can enhance this)
        if request.is_json:
            sanitized_data = _sanitize_dict(request.get_json())
            # Replace request data with sanitized version
            request._cached_json = sanitized_data

        return f(*args, **kwargs)

    return decorated_function


def require_https(f):
    """Decorator to require HTTPS in production"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_app.config.get("ENV") == "production":
            if not request.is_secure:
                abort(400, message="HTTPS required in production")
        return f(*args, **kwargs)

    return decorated_function


def cache_response(expiry: int = 300, key_func: Optional[Callable] = None):
    """Response caching decorator

    Args:
        expiry: Cache expiry time in seconds
        key_func: Function to generate cache key
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Generate cache key
            if key_func:
                cache_key = key_func()
            else:
                cache_key = f"response:{request.endpoint}:{request.args.get('page', 1)}"

            # Try to get from cache
            try:
                cached_response = redis_client.get(cache_key)
                if cached_response:
                    return cached_response
            except Exception as e:
                if logger:
                    logger.warning(f"Cache lookup failed: {str(e)}")

            # Execute function and cache result
            result = f(*args, **kwargs)

            try:
                redis_client.setex(cache_key, expiry, result)
            except Exception as e:
                if logger:
                    logger.warning(f"Cache storage failed: {str(e)}")

            return result

        return decorated_function

    return decorator


def log_activity(activity_type: str):
    """Activity logging decorator for audit trails"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            start_time = time.time()

            try:
                result = f(*args, **kwargs)

                # Log successful activity
                _log_activity(activity_type, "success", time.time() - start_time)

                return result
            except Exception as e:
                # Log failed activity
                _log_activity(activity_type, "failed", time.time() - start_time, str(e))
                raise

        return decorated_function

    return decorator


def require_permission(permission: str):
    """Permission-based access control decorator"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401, message="Authentication required")

            # Check if user has the required permission
            if not _has_permission(current_user, permission):
                abort(403, message=f"Permission '{permission}' required")

            return f(*args, **kwargs)

        return decorated_function

    return decorator


# ==================== PRIVATE HELPER FUNCTIONS ====================


def _sanitize_dict(data: dict) -> dict:
    """Recursively sanitize dictionary values"""
    if not isinstance(data, dict):
        return _sanitize_string(data)

    sanitized = {}
    for key, value in data.items():
        if isinstance(value, dict):
            sanitized[key] = _sanitize_dict(value)
        elif isinstance(value, list):
            sanitized[key] = [
                _sanitize_string(item) if isinstance(item, str) else item
                for item in value
            ]
        else:
            sanitized[key] = _sanitize_string(value)

    return sanitized


def _sanitize_string(value: Any) -> Any:
    """Sanitize string values to prevent XSS"""
    if not isinstance(value, str):
        return value

    import html

    # HTML escape to prevent XSS
    sanitized = html.escape(value)

    # Remove potentially dangerous patterns
    dangerous_patterns = [
        r"<script.*?>.*?</script>",
        r"javascript:",
        r"data:text/html",
        r"vbscript:",
        r"on\w+\s*=",
    ]

    import re

    for pattern in dangerous_patterns:
        sanitized = re.sub(pattern, "", sanitized, flags=re.IGNORECASE)

    return sanitized.strip()


def _log_activity(
    activity_type: str, status: str, duration: float, error: Optional[str] = None
):
    """Log user activity for audit trails"""
    if not logger:
        return

    log_data = {
        "activity_type": activity_type,
        "status": status,
        "duration": duration,
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": current_user.id if current_user.is_authenticated else None,
        "ip_address": request.remote_addr,
        "user_agent": request.headers.get("User-Agent"),
        "endpoint": request.endpoint,
        "method": request.method,
    }

    if error:
        log_data["error"] = error

    logger.info(f"Activity: {log_data}")


def _has_permission(user, permission: str) -> bool:
    """Check if user has the required permission"""
    # This is a simplified implementation
    # In a real system, you'd have a proper permission system

    # Admin users have all permissions
    if hasattr(user, "is_admin") and user.is_admin:
        return True

    # Role-based permissions
    permission_map = {
        "product.create": user.is_seller,
        "product.update": user.is_seller,
        "product.delete": user.is_seller,
        "order.view": user.is_buyer or user.is_seller,
        "order.create": user.is_buyer,
        "order.update": user.is_seller,
        "payment.process": user.is_buyer,
        "payment.view": user.is_buyer or user.is_seller,
        "niche.create": user.is_seller,
        "niche.moderate": user.is_seller,
        "user.manage": user.is_admin,
    }

    return permission_map.get(permission, False)


# ==================== COMPOSITE DECORATORS ====================


def secure_endpoint(rate_limit_requests: int = 60, cache_expiry: int = 300):
    """Composite decorator for secure endpoints with rate limiting and caching"""

    def decorator(f):
        @wraps(f)
        @login_required
        @rate_limit(rate_limit_requests)
        @sanitize_input
        @cache_response(cache_expiry)
        def decorated_function(*args, **kwargs):
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def admin_only(f):
    """Decorator for admin-only endpoints"""

    @wraps(f)
    @login_required
    @require_permission("user.manage")
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)

    return decorated_function


def seller_endpoint(rate_limit_requests: int = 30):
    """Decorator for seller-specific endpoints"""

    def decorator(f):
        @wraps(f)
        @seller_required
        @rate_limit(rate_limit_requests)
        @log_activity("seller_action")
        def decorated_function(*args, **kwargs):
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def buyer_endpoint(rate_limit_requests: int = 60):
    """Decorator for buyer-specific endpoints"""

    def decorator(f):
        @wraps(f)
        @buyer_required
        @rate_limit(rate_limit_requests)
        @log_activity("buyer_action")
        def decorated_function(*args, **kwargs):
            return f(*args, **kwargs)

        return decorated_function

    return decorator
