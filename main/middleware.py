from flask import request, g
from functools import wraps
from main.config import settings
import logging
from main.error import APIError

logger = logging.getLogger(__name__)


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        # Pre-request processing
        logger.info(
            f"Incoming request: {environ['REQUEST_METHOD']} {environ['PATH_INFO']}"
        )
        # Make sure to pass the request through
        return self.app(environ, start_response)


def role_required(role):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not getattr(g.user, f"is_{role}", False):
                raise APIError(f"{role} role required", 403)
            return f(*args, **kwargs)

        return wrapped

    return decorator
