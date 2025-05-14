from functools import wraps
from flask import abort
from flask_login import current_user
from .errors import ForbiddenError


def buyer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_buyer:
            raise ForbiddenError(message="Only buyers can access this endpoint")
        return f(*args, **kwargs)

    return decorated_function


def seller_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_seller:
            raise ForbiddenError(message="Only sellers can access this endpoint")
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # TODO: Implement admin check
        raise ForbiddenError(message="Admin access required")
        return f(*args, **kwargs)

    return decorated_function
