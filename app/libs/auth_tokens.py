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


def verify_auth_token_with_timestamp(token: str):
    """Like verify_auth_token but also returns when the token was issued.

    Returns ``(user_id, issued_at)`` for a valid token or ``(None, None)``
    otherwise. ``issued_at`` (a timezone-aware UTC datetime from itsdangerous)
    lets the request loader enforce force-logout: a token minted before a
    user's ``tokens_valid_from`` is rejected even though its signature is
    still valid and unexpired."""
    try:
        user_id, issued_at = _serializer().loads(
            token, max_age=TOKEN_MAX_AGE_SECONDS, return_timestamp=True
        )
        return user_id, issued_at
    except (BadSignature, SignatureExpired):
        return None, None
