"""Server-side verification of Google and Apple identity tokens.

The mobile app sends the identity token it received from the provider. That
token is a *carrier*, never a claim we trust: anyone can POST a hand-written
JSON blob to this endpoint. Every token is verified against the provider's own
published signing keys before a single field in it is believed.

What "verified" means here, for both providers:

  signature   RS256 against the provider's current JWKS
  iss         the provider's issuer, exactly
  aud         one of *our* client IDs -- this is what stops a token minted for
              somebody else's app being replayed against ours, and it is the
              check most commonly left out
  exp / iat   not expired, not issued in the future
  nonce       matches the nonce the app generated for this attempt (Apple), so
              a token captured from an earlier sign-in cannot be replayed

Keys are fetched from the provider and cached by PyJWKClient, which also
handles key rotation: an unknown `kid` triggers a refetch rather than a failure.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import jwt
from jwt import PyJWKClient

from app.libs.errors import APIError

logger = logging.getLogger(__name__)

GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URI = "https://appleid.apple.com/auth/keys"

# Small clock tolerance. Phones drift, and rejecting a token because the device
# is three seconds fast is a support ticket, not security.
LEEWAY_SECONDS = 10

# Cached across requests -- these fetch over the network, and a cold client on
# every sign-in would add a round trip to Google or Apple to every login.
_jwk_clients: Dict[str, PyJWKClient] = {}


def _normalise_email(value):
    """Same rule as the schema layer (see NormalisedEmail in schemas.py).

    Provider claims do not pass through a marshmallow schema, so without this
    a Google identity asserting "Ada@example.com" would fail to match the
    account stored as "ada@example.com" and create a second one.
    """
    return value.strip().lower() if isinstance(value, str) else value


class OAuthError(APIError):
    """A provider token we could not verify, or chose not to trust."""

    def __init__(
        self, message: str, status_code: int = 401, code: str = "OAUTH_INVALID"
    ):
        super().__init__(message, status_code)
        self.code = code


def _client(jwks_uri: str) -> PyJWKClient:
    if jwks_uri not in _jwk_clients:
        # lifespan: how long a fetched key set is reused before refetching.
        _jwk_clients[jwks_uri] = PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600)
    return _jwk_clients[jwks_uri]


def _decode(
    token: str,
    *,
    jwks_uri: str,
    issuers: tuple,
    audiences: list,
    nonce: Optional[str] = None,
) -> Dict[str, Any]:
    if not token or not isinstance(token, str):
        raise OAuthError("No identity token supplied.")

    if not audiences or not any(audiences):
        # Refusing here rather than skipping the audience check: an unset client
        # id must fail loudly at sign-in, not silently accept tokens minted for
        # any app in the world.
        raise OAuthError(
            "Social sign-in is not configured on this server.",
            status_code=503,
            code="OAUTH_NOT_CONFIGURED",
        )

    try:
        signing_key = _client(jwks_uri).get_signing_key_from_jwt(token)
    except Exception as exc:  # network, malformed token, unknown kid
        logger.warning("oauth: could not resolve signing key: %s", exc)
        raise OAuthError("Could not verify that sign-in. Please try again.")

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=[a for a in audiences if a],
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise OAuthError(
            "That sign-in has expired. Please try again.", code="OAUTH_EXPIRED"
        )
    except jwt.InvalidAudienceError:
        # Deliberately not echoed to the client: the audience is our client id.
        logger.warning("oauth: token audience did not match any configured client id")
        raise OAuthError(
            "That sign-in was not issued for this app.", code="OAUTH_BAD_AUDIENCE"
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("oauth: invalid token: %s", exc)
        raise OAuthError("Could not verify that sign-in. Please try again.")

    if claims.get("iss") not in issuers:
        raise OAuthError("That sign-in came from an unexpected issuer.")

    # Apple echoes the nonce the app generated. Checking it is what stops a
    # token lifted from an earlier session being replayed.
    if nonce is not None:
        if claims.get("nonce") != nonce:
            raise OAuthError("That sign-in could not be matched to this attempt.")

    if not claims.get("sub"):
        raise OAuthError("That sign-in did not identify a user.")

    return claims


def verify_google(
    token: str, *, audiences: list, nonce: Optional[str] = None
) -> Dict[str, Any]:
    """Verify a Google ID token and return a normalised identity."""
    claims = _decode(
        token,
        jwks_uri=GOOGLE_JWKS_URI,
        issuers=GOOGLE_ISSUERS,
        audiences=audiences,
        nonce=nonce,
    )
    return {
        "provider": "google",
        "sub": claims["sub"],
        "email": _normalise_email(claims.get("email")),
        # Google sends this as a real bool or the string "true" depending on
        # the endpoint. Normalised here so callers get one type.
        "email_verified": claims.get("email_verified") in (True, "true"),
        "name": claims.get("name"),
    }


def verify_apple(
    token: str, *, audiences: list, nonce: Optional[str] = None
) -> Dict[str, Any]:
    """Verify an Apple identity token and return a normalised identity.

    Apple never sends a name in the token -- it is returned once, beside the
    token, on first authorisation only, so the caller passes it in separately.
    """
    claims = _decode(
        token,
        jwks_uri=APPLE_JWKS_URI,
        issuers=(APPLE_ISSUER,),
        audiences=audiences,
        nonce=nonce,
    )
    email = _normalise_email(claims.get("email"))
    return {
        "provider": "apple",
        "sub": claims["sub"],
        "email": email,
        "email_verified": claims.get("email_verified") in (True, "true"),
        # A private-relay address forwards to the user's real inbox but can be
        # revoked from Apple's settings at any time. Flagged so we never treat
        # one as a durable identifier or a way to reach someone long-term.
        "is_private_relay": bool(email and email.endswith("@privaterelay.appleid.com")),
        "name": None,
    }
