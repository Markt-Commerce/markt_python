"""Admin console support: staff sign-in/out, resend-verification error
mapping, and the admin profile-picture upload.

Service tests run against mocked session scopes; HTTP tests drive the routes
with the service layer patched out, mirroring tests/test_admin_users.py.
"""

import re
from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from main.setup import create_app

from app.admin.auth_services import AdminAuthService
from app.admin.services import AdminUserService
from app.libs.errors import (
    APIError,
    AuthError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.media.errors import MediaUploadError
from app.users.models import User
from app.users.verification import VerificationThrottled


def _user(password="right", **kwargs):
    defaults = dict(
        id="ADM_1",
        email="staff@markt.co",
        username="staff",
        is_active=True,
        email_verified=True,
        is_buyer=False,
        is_seller=False,
        is_admin=False,
        admin_role="support",
    )
    defaults.update(kwargs)
    u = User(**defaults)
    u.check_password = lambda p: p == password
    return u


def _scope_with(mock_scope, user):
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = user
    session.query.return_value.get.return_value = user
    mock_scope.return_value.__enter__.return_value = session
    return session


# --- AdminAuthService.login ----------------------------------------------


@patch("app.admin.auth_services.generate_auth_token", return_value="tok")
@patch("app.admin.auth_services.session_scope")
def test_staff_without_buyer_or_seller_account_can_sign_in(mock_scope, _tok):
    user = _user()
    session = _scope_with(mock_scope, user)

    result = AdminAuthService.login("staff@markt.co", "right")

    assert result["access_token"] == "tok"
    assert result["admin_role"] == "support"
    assert "user.view" in result["permissions"]
    assert isinstance(user.last_login_at, datetime)
    session.add.assert_called_once()  # the admin.login audit row


@patch("app.admin.auth_services.session_scope")
def test_wrong_password_is_invalid_credentials(mock_scope):
    _scope_with(mock_scope, _user())
    with pytest.raises(AuthError) as exc:
        AdminAuthService.login("staff@markt.co", "wrong")
    assert re.search("Invalid credentials", exc.value.message)


@patch("app.admin.auth_services.session_scope")
def test_unknown_email_is_invalid_credentials(mock_scope):
    _scope_with(mock_scope, None)
    with pytest.raises(AuthError) as exc:
        AdminAuthService.login("nobody@markt.co", "right")
    assert re.search("Invalid credentials", exc.value.message)


@patch("app.admin.auth_services.session_scope")
def test_non_staff_is_forbidden(mock_scope):
    _scope_with(mock_scope, _user(admin_role=None, is_buyer=True))
    with pytest.raises(ForbiddenError) as exc:
        AdminAuthService.login("staff@markt.co", "right")
    assert re.search("does not have admin access", exc.value.message)


@pytest.mark.parametrize(
    "state, message",
    [
        ({"banned_at": datetime.utcnow()}, "Account is banned"),
        ({"suspended_at": datetime.utcnow()}, "Account is suspended"),
        ({"is_active": False}, "Account is deactivated"),
    ],
)
@patch("app.admin.auth_services.session_scope")
def test_blocked_staff_cannot_sign_in(mock_scope, state, message):
    _scope_with(mock_scope, _user(**state))
    with pytest.raises(AuthError) as exc:
        AdminAuthService.login("staff@markt.co", "right")
    assert re.search(message, exc.value.message)


@patch("app.users.services.AuthService.send_email_verification")
@patch("app.admin.auth_services.session_scope")
def test_unverified_staff_is_refused_without_sending_a_code(mock_scope, mock_send):
    _scope_with(mock_scope, _user(email_verified=False))
    with pytest.raises(ForbiddenError) as exc:
        AdminAuthService.login("staff@markt.co", "right")
    assert re.search("not verified", exc.value.message)
    mock_send.assert_not_called()


# --- AdminAuthService.logout ---------------------------------------------


@patch("app.admin.auth_services.session_scope")
def test_logout_revokes_every_token(mock_scope):
    user = _user()
    session = _scope_with(mock_scope, user)

    AdminAuthService.logout("ADM_1")

    assert user.tokens_valid_from is not None
    assert user.is_token_revoked(datetime(2000, 1, 1)) is True
    session.add.assert_called_once()  # the admin.logout audit row


# --- resend verification error mapping ------------------------------------


def _unverified_target(mock_read):
    target = _user(id="USR_9", admin_role=None, email_verified=False)
    session = MagicMock()
    session.query.return_value.get.return_value = target
    mock_read.return_value.__enter__.return_value = session


@patch("app.users.services.AuthService.send_email_verification")
@patch("app.admin.services.read_scope")
def test_resend_mail_failure_is_503_not_401(mock_read, mock_send):
    _unverified_target(mock_read)
    mock_send.side_effect = AuthError("Failed to send verification email")
    with pytest.raises(APIError) as exc:
        AdminUserService.resend_verification(_user(is_admin=True), "USR_9")
    assert exc.value.status_code == 503


@patch("app.users.services.AuthService.send_email_verification")
@patch("app.admin.services.read_scope")
def test_resend_race_on_verified_email_is_422(mock_read, mock_send):
    _unverified_target(mock_read)
    mock_send.side_effect = AuthError("Email already verified")
    with pytest.raises(ValidationError):
        AdminUserService.resend_verification(_user(is_admin=True), "USR_9")


@patch("app.users.services.AuthService.send_email_verification")
@patch("app.admin.services.read_scope")
def test_resend_target_vanishing_is_404(mock_read, mock_send):
    _unverified_target(mock_read)
    mock_send.side_effect = AuthError("User not found")
    with pytest.raises(NotFoundError):
        AdminUserService.resend_verification(_user(is_admin=True), "USR_9")


# --- profile picture upload ----------------------------------------------


@patch("app.media.services.media_service._validate_image")
@patch("app.admin.services.read_scope")
def test_unusable_image_is_422(mock_read, mock_validate):
    _unverified_target(mock_read)
    mock_validate.side_effect = MediaUploadError("Unsupported image format: .bmp")
    with pytest.raises(ValidationError) as exc:
        AdminUserService.upload_profile_picture(
            _user(is_admin=True), "USR_9", BytesIO(b"x"), "a.bmp"
        )
    assert re.search("Unsupported image format", exc.value.message)


@patch("app.users.services.UserService.upload_profile_picture")
@patch("app.media.services.media_service._validate_image")
@patch("app.admin.services.read_scope")
def test_storage_failure_is_503(mock_read, _validate, mock_upload):
    _unverified_target(mock_read)
    mock_upload.side_effect = AuthError("Failed to upload profile picture: s3")
    with pytest.raises(APIError) as exc:
        AdminUserService.upload_profile_picture(
            _user(is_admin=True), "USR_9", BytesIO(b"x"), "a.png"
        )
    assert exc.value.status_code == 503


@patch("app.admin.services.session_scope")
@patch("app.users.services.UserService.upload_profile_picture")
@patch("app.media.services.media_service._validate_image")
@patch("app.admin.services.read_scope")
def test_upload_sets_picture_and_audits(mock_read, _validate, mock_upload, mock_scope):
    _unverified_target(mock_read)
    stored = _user(id="USR_9", admin_role=None, profile_picture="https://cdn/p.png")
    session = MagicMock()
    session.query.return_value.get.return_value = stored
    mock_scope.return_value.__enter__.return_value = session

    result = AdminUserService.upload_profile_picture(
        _user(is_admin=True), "USR_9", BytesIO(b"x"), "a.png"
    )

    mock_upload.assert_called_once()
    assert result["profile_picture"] == "https://cdn/p.png"
    session.add.assert_called_once()


# --- HTTP ----------------------------------------------------------------


@pytest.fixture
def client():
    flask_app, _socketio = create_app()
    flask_app.config["TESTING"] = True
    # Keep the login rate limiter off the real Redis; it fails open.
    with patch("app.libs.decorators.redis_client", MagicMock()):
        yield flask_app.test_client()


def _authed(**kwargs):
    user = MagicMock()
    user.is_authenticated = True
    for k, v in kwargs.items():
        setattr(user, k, v)
    return user


@patch("app.admin.routes.AdminAuthService.login")
def test_login_route_returns_token_and_permissions(mock_login, client):
    mock_login.return_value = {
        "user_id": "ADM_1",
        "email": "staff@markt.co",
        "is_admin": False,
        "is_super_admin": False,
        "admin_role": "support",
        "permissions": ["user.view"],
        "access_token": "tok",
    }
    resp = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "Staff@Markt.co", "password": "right"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["access_token"] == "tok"
    # NormalisedEmail lower-cases before the service sees it.
    mock_login.assert_called_once_with("staff@markt.co", "right")


@patch("app.admin.routes.AdminAuthService.login")
def test_login_route_maps_non_staff_to_403(mock_login, client):
    mock_login.side_effect = ForbiddenError("This account does not have admin access")
    resp = client.post(
        "/api/v1/admin/auth/login", json={"email": "a@b.co", "password": "x"}
    )
    assert resp.status_code == 403
    assert resp.get_json()["message"] == "This account does not have admin access"


def test_login_route_validates_body(client):
    resp = client.post("/api/v1/admin/auth/login", json={"email": "a@b.co"})
    assert resp.status_code == 422


def test_logout_requires_auth(client):
    assert client.post("/api/v1/admin/auth/logout").status_code == 401


@patch("app.admin.routes.AdminAuthService.logout")
@patch("flask_login.utils._get_user")
def test_logout_revokes_for_current_user(mock_get_user, mock_logout, client):
    mock_get_user.return_value = _authed(id="ADM_1", is_admin=False)
    resp = client.post("/api/v1/admin/auth/logout")
    assert resp.status_code == 204
    mock_logout.assert_called_once_with("ADM_1")


@patch("app.admin.routes.AdminUserService.resend_verification")
@patch("flask_login.utils._get_user")
def test_resend_throttle_is_429_with_retry_after(mock_get_user, mock_resend, client):
    mock_get_user.return_value = _authed(is_admin=False, admin_role="support")
    mock_resend.side_effect = VerificationThrottled("Slow down", retry_after=60)
    resp = client.post("/api/v1/admin/users/USR_9/resend-verification")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"
    assert resp.get_json()["message"] == "Slow down"


@patch("flask_login.utils._get_user")
def test_profile_picture_needs_a_file(mock_get_user, client):
    mock_get_user.return_value = _authed(is_admin=False, admin_role="support")
    resp = client.post("/api/v1/admin/users/USR_9/profile-picture", data={})
    assert resp.status_code == 400


@patch("flask_login.utils._get_user")
def test_profile_picture_gated_by_user_edit(mock_get_user, client):
    # Moderation can suspend and ban but not edit profiles.
    mock_get_user.return_value = _authed(is_admin=False, admin_role="moderation")
    resp = client.post(
        "/api/v1/admin/users/USR_9/profile-picture",
        data={"file": (BytesIO(b"x"), "a.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 403
