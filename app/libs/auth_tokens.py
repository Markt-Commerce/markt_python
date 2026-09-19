"""Stateless bearer tokens for API clients (e.g. the React Native app) that
can't rely on Flask session cookies.

Cookies are unreliable in React Native's fetch (they aren't persisted across
app restarts), so mobile requests carry an ``Authorization: Bearer <token>``
header instead. The token is just the user id signed with the app SECRET_KEY
via itsdangerous, so verification is stateless -- no server-side session store.
"""

from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

_SALT = "markt-auth-token"

# 30 days. Comfortably outlives the mobile app's 7-day stored user_session so a
# returning user's token is still valid when the app rehydrates its session.
TOKEN_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


def _serializer() -> URLSafeTimedSerializer:
    # Read the key lazily from the live app config so this module has no
    # import-time dependency on settings.
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_SALT)


def generate_auth_token(user_id: str) -> str:
    """Sign a user id into an opaque bearer token."""
    return _serializer().dumps(user_id)


def verify_auth_token(token: str):
    """Return the user id embedded in a valid token, or None if it is invalid
    or expired."""
    try:
        return _serializer().loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
