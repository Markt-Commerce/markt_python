"""Verification of Google and Apple identity tokens, and account linking.

These tests mint **real RSA-signed JWTs** and serve a **real JWKS** rather than
mocking `jwt.decode`. Mocking the decoder would test that we call a library,
not that a tampered or misaddressed token is actually rejected -- and rejecting
those is the entire security value of this endpoint.
"""

import json
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.users import oauth
from app.users.oauth import OAuthError, verify_apple, verify_google

KID = "test-key-1"
GOOGLE_AUD = "111-web.apps.googleusercontent.com"
APPLE_AUD = "com.markt.app"


@pytest.fixture(scope="module")
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _clear_jwk_cache():
    """The client is cached across requests in production, which is correct --
    but a leaked client between tests would hide a key-resolution bug."""
    oauth._jwk_clients.clear()
    yield
    oauth._jwk_clients.clear()


def _sign(keypair, claims, *, kid=KID, alg="RS256"):
    return jwt.encode(claims, keypair, algorithm=alg, headers={"kid": kid})


def _serve_jwks(keypair):
    """Patch PyJWKClient so it resolves our test key instead of hitting the
    network, while leaving all of jwt.decode's real verification in place."""
    signing_key = MagicMock()
    signing_key.key = keypair.public_key()
    client = MagicMock()
    client.get_signing_key_from_jwt.return_value = signing_key
    return patch.object(oauth, "_client", return_value=client)


def _google_claims(**over):
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": GOOGLE_AUD,
        "sub": "google-sub-123",
        "email": "ada@example.com",
        "email_verified": True,
        "name": "Ada Obi",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(over)
    return claims


def _apple_claims(**over):
    now = int(time.time())
    claims = {
        "iss": "https://appleid.apple.com",
        "aud": APPLE_AUD,
        "sub": "apple-sub-456",
        "email": "ada@example.com",
        "email_verified": "true",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(over)
    return claims


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_valid_google_token_is_accepted(keypair):
    token = _sign(keypair, _google_claims())
    with _serve_jwks(keypair):
        identity = verify_google(token, audiences=[GOOGLE_AUD])
    assert identity["provider"] == "google"
    assert identity["sub"] == "google-sub-123"
    assert identity["email"] == "ada@example.com"
    assert identity["email_verified"] is True


def test_valid_apple_token_is_accepted(keypair):
    token = _sign(keypair, _apple_claims())
    with _serve_jwks(keypair):
        identity = verify_apple(token, audiences=[APPLE_AUD])
    assert identity["sub"] == "apple-sub-456"
    # Apple sends this as the *string* "true"; normalised to a bool.
    assert identity["email_verified"] is True


def test_apple_private_relay_is_flagged(keypair):
    """A relay address forwards to the real inbox but can be revoked at any
    time, so it must never be treated as a durable way to reach someone."""
    token = _sign(keypair, _apple_claims(email="abc123@privaterelay.appleid.com"))
    with _serve_jwks(keypair):
        identity = verify_apple(token, audiences=[APPLE_AUD])
    assert identity["is_private_relay"] is True


# ---------------------------------------------------------------------------
# The rejections -- each one is a real attack, not a formality
# ---------------------------------------------------------------------------


def test_expired_token_is_rejected(keypair):
    now = int(time.time())
    token = _sign(keypair, _google_claims(iat=now - 7200, exp=now - 3600))
    with _serve_jwks(keypair), pytest.raises(OAuthError) as exc:
        verify_google(token, audiences=[GOOGLE_AUD])
    assert exc.value.code == "OAUTH_EXPIRED"


def test_token_for_another_app_is_rejected(keypair):
    """The check most often left out. Without it, an identity token minted for
    any other Google app could be replayed here to impersonate its subject."""
    token = _sign(
        keypair, _google_claims(aud="999-someone-else.apps.googleusercontent.com")
    )
    with _serve_jwks(keypair), pytest.raises(OAuthError) as exc:
        verify_google(token, audiences=[GOOGLE_AUD])
    assert exc.value.code == "OAUTH_BAD_AUDIENCE"


def test_tampered_payload_is_rejected(keypair):
    """Flip a claim after signing: the signature must no longer verify."""
    token = _sign(keypair, _google_claims())
    header, payload, sig = token.split(".")
    import base64

    raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    body = json.loads(raw)
    body["sub"] = "attacker-sub"
    forged = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()

    with _serve_jwks(keypair), pytest.raises(OAuthError):
        verify_google(f"{header}.{forged}.{sig}", audiences=[GOOGLE_AUD])


def test_token_signed_by_the_wrong_key_is_rejected(keypair):
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _sign(attacker, _google_claims())
    with _serve_jwks(keypair), pytest.raises(OAuthError):
        verify_google(token, audiences=[GOOGLE_AUD])


def test_unsigned_token_is_rejected(keypair):
    """alg=none is the classic JWT bypass. `algorithms=["RS256"]` closes it."""
    token = jwt.encode(_google_claims(), key=None, algorithm="none")
    with _serve_jwks(keypair), pytest.raises(OAuthError):
        verify_google(token, audiences=[GOOGLE_AUD])


def test_wrong_issuer_is_rejected(keypair):
    token = _sign(keypair, _google_claims(iss="https://evil.example.com"))
    with _serve_jwks(keypair), pytest.raises(OAuthError):
        verify_google(token, audiences=[GOOGLE_AUD])


def test_nonce_mismatch_is_rejected(keypair):
    """Stops a token captured from an earlier sign-in being replayed."""
    token = _sign(keypair, _apple_claims(nonce="nonce-from-an-old-attempt"))
    with _serve_jwks(keypair), pytest.raises(OAuthError):
        verify_apple(token, audiences=[APPLE_AUD], nonce="nonce-for-this-attempt")


def test_matching_nonce_is_accepted(keypair):
    token = _sign(keypair, _apple_claims(nonce="n-1"))
    with _serve_jwks(keypair):
        identity = verify_apple(token, audiences=[APPLE_AUD], nonce="n-1")
    assert identity["sub"] == "apple-sub-456"


def test_unconfigured_audience_refuses_rather_than_skipping_the_check(keypair):
    """An unset client id must fail loudly. Skipping the audience check would
    silently accept tokens minted for any app in the world."""
    token = _sign(keypair, _google_claims())
    with _serve_jwks(keypair), pytest.raises(OAuthError) as exc:
        verify_google(token, audiences=[])
    assert exc.value.code == "OAUTH_NOT_CONFIGURED"
    assert exc.value.status_code == 503


def test_missing_token_is_rejected():
    with pytest.raises(OAuthError):
        verify_google("", audiences=[GOOGLE_AUD])


# ---------------------------------------------------------------------------
# Account linking -- the policy chosen in planning
# ---------------------------------------------------------------------------

from app.users.models import SocialAccount, User  # noqa: E402
from app.users.services import SocialAuthService  # noqa: E402


def _scope(session):
    scope = MagicMock()
    scope.__enter__ = MagicMock(return_value=session)
    scope.__exit__ = MagicMock(return_value=False)
    return scope


def _session(*, link=None, user_by_email=None, user_by_id=None):
    """A session whose three lookups (link, user-by-email, user-by-id) can each
    be pointed at a row or at nothing."""
    session = MagicMock()
    added = []
    session.add.side_effect = added.append
    session.added = added

    def query(model):
        q = MagicMock()
        if model is SocialAccount:
            q.filter_by.return_value.first.return_value = link
        elif model is User:
            q.filter.return_value.first.return_value = user_by_email
            q.get.return_value = user_by_id
            # username-collision probe: nothing taken
            q.filter.return_value.first.side_effect = None
        return q

    session.query.side_effect = query
    return session


def _identity(**over):
    base = {
        "provider": "google",
        "sub": "google-sub-123",
        "email": "ada@example.com",
        "email_verified": True,
        "name": "Ada Obi",
    }
    base.update(over)
    return base


def test_known_identity_signs_the_same_user_in(keypair):
    """Checked before email, so a user who changed their address still lands
    on their own account."""
    user = User()
    user.id = "USR_1"
    link = SocialAccount()
    link.user_id = "USR_1"
    session = _session(link=link, user_by_id=user)

    with patch.object(
        SocialAuthService, "__module__", SocialAuthService.__module__
    ), patch("app.users.services.session_scope", return_value=_scope(session)):
        result, created = SocialAuthService.authenticate(_identity())

    assert result is user
    assert created is False


def test_verified_email_collision_auto_links():
    existing = User()
    existing.id = "USR_9"
    existing.email = "ada@example.com"
    session = _session(link=None, user_by_email=existing)

    with patch("app.users.services.session_scope", return_value=_scope(session)):
        result, created = SocialAuthService.authenticate(_identity(email_verified=True))

    assert result is existing
    assert created is False
    assert any(isinstance(o, SocialAccount) for o in session.added), "link not created"
    # A provider that verified the address is better evidence than our own
    # unfinished email loop.
    assert existing.email_verified is True


def test_unverified_email_collision_refuses_to_link():
    """The account-takeover vector this policy exists to close: signing up to a
    provider with someone else's unverified address must not inherit their
    Markt account."""
    from app.libs.errors import ConflictError

    existing = User()
    existing.id = "USR_9"
    session = _session(link=None, user_by_email=existing)

    with patch("app.users.services.session_scope", return_value=_scope(session)):
        with pytest.raises(ConflictError):
            SocialAuthService.authenticate(_identity(email_verified=False))

    assert not any(isinstance(o, SocialAccount) for o in session.added)


def test_new_identity_creates_a_passwordless_user():
    session = _session(link=None, user_by_email=None)

    with patch("app.users.services.session_scope", return_value=_scope(session)):
        user, created = SocialAuthService.authenticate(
            _identity(email="new@example.com")
        )

    assert created is True
    assert user.email == "new@example.com"
    # No placeholder secret: password_hash is already nullable.
    assert user.password_hash is None
    assert user.username and len(user.username) >= 3


def test_identity_without_an_email_is_refused():
    """Better than inventing a placeholder address that can never receive mail."""
    from app.libs.errors import ValidationError as VErr

    session = _session(link=None, user_by_email=None)
    with patch("app.users.services.session_scope", return_value=_scope(session)):
        with pytest.raises(VErr):
            SocialAuthService.authenticate(_identity(email=None))


def test_unknown_provider_is_refused():
    from app.libs.errors import ValidationError as VErr

    with pytest.raises(VErr):
        SocialAuthService.authenticate(_identity(provider="facebook"))
