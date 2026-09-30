"""Increment 2: §1 admin user management.

Model-level tests for the new account-control state (pure, no DB), service
tests with mocked session scopes, and HTTP tests for the permission gates.
Run in the Docker/CI env -- these import the full ORM stack.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from main.setup import create_app

from app.admin.services import AdminUserService, _account_status
from app.libs.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.users.models import User


def _user(**kwargs):
    defaults = dict(id="USR_1", email="a@b.co", username="ada", is_active=True)
    defaults.update(kwargs)
    return User(**defaults)


# --- model: account-control state ----------------------------------------


def test_suspend_and_unsuspend_roundtrip():
    u = _user()
    assert u.is_suspended is False and u.is_login_blocked is False
    u.suspend("payment dispute")
    assert u.is_suspended is True
    assert u.suspension_reason == "payment dispute"
    assert u.is_login_blocked is True
    u.unsuspend()
    assert u.is_suspended is False and u.suspension_reason is None
    assert u.is_login_blocked is False


def test_ban_and_unban_roundtrip():
    u = _user()
    u.ban("counterfeit goods")
    assert u.is_banned is True and u.is_login_blocked is True
    u.unban()
    assert u.is_banned is False and u.ban_reason is None
    assert u.is_login_blocked is False


def test_deleted_account_is_login_blocked():
    u = _user(deleted_at=datetime.utcnow())
    assert u.is_login_blocked is True


def test_account_status_reports_strongest_state():
    u = _user()
    assert _account_status(u) == "active"
    u.is_active = False
    assert _account_status(u) == "deactivated"
    u.suspend()
    assert _account_status(u) == "suspended"
    u.ban()
    assert _account_status(u) == "banned"  # ban outranks suspend
    u.deleted_at = datetime.utcnow()
    assert _account_status(u) == "deleted"  # deletion outranks all


def test_token_revocation_compares_tz_aware_and_naive_safely():
    u = _user()
    aware_now = datetime.now(timezone.utc)
    # No epoch set -> nothing revoked.
    assert u.is_token_revoked(aware_now) is False
    # Force-logout: tokens issued before the epoch are revoked, later ones not.
    u.revoke_tokens()
    assert u.is_token_revoked(aware_now - timedelta(hours=1)) is True
    assert u.is_token_revoked(aware_now + timedelta(hours=1)) is False
    assert u.is_token_revoked(None) is False


# --- service: mutations with mocked scopes --------------------------------


def _mock_session(user=None, clash=None):
    session = MagicMock()
    session.query.return_value.get.return_value = user
    session.query.return_value.filter.return_value.first.return_value = clash
    return session


def _patch_session(mock_scope, session):
    mock_scope.return_value.__enter__.return_value = session


@patch("app.admin.services.session_scope")
def test_suspend_user_sets_state_and_audits(mock_scope):
    actor = _user(id="ADM_1", admin_role="moderation")
    target = _user(id="USR_9")
    session = _mock_session(user=target)
    _patch_session(mock_scope, session)

    result = AdminUserService.suspend_user(actor, "USR_9", "spam")

    assert target.is_suspended is True
    assert result["status"] == "suspended"
    # one row added: the audit entry
    assert session.add.call_count == 1


@patch("app.admin.services.session_scope")
def test_cannot_action_your_own_account(mock_scope):
    actor = _user(id="ADM_1", admin_role="moderation")
    session = _mock_session(user=actor)
    _patch_session(mock_scope, session)
    with pytest.raises(ForbiddenError):
        AdminUserService.ban_user(actor, "ADM_1", "nope")


@patch("app.admin.services.session_scope")
def test_scoped_admin_cannot_action_a_privileged_account(mock_scope):
    actor = _user(id="ADM_1", admin_role="moderation")  # not super_admin
    target = _user(id="ADM_2", is_admin=True)
    session = _mock_session(user=target)
    _patch_session(mock_scope, session)
    with pytest.raises(ForbiddenError):
        AdminUserService.suspend_user(actor, "ADM_2")


@patch("app.admin.services.session_scope")
def test_super_admin_may_action_a_privileged_account(mock_scope):
    actor = _user(id="ADM_0", is_admin=True)  # super
    target = _user(id="ADM_2", admin_role="finance")
    session = _mock_session(user=target)
    _patch_session(mock_scope, session)
    result = AdminUserService.suspend_user(actor, "ADM_2")
    assert result["status"] == "suspended"


@patch("app.admin.services.session_scope")
def test_missing_user_is_404(mock_scope):
    actor = _user(id="ADM_1", is_admin=True)
    session = _mock_session(user=None)
    _patch_session(mock_scope, session)
    with pytest.raises(NotFoundError):
        AdminUserService.suspend_user(actor, "USR_GONE")


@patch("app.admin.services.session_scope")
def test_edit_profile_rejects_duplicate_username(mock_scope):
    actor = _user(id="ADM_1", is_admin=True)
    target = _user(id="USR_9", username="ada")
    clash = _user(id="USR_X", username="grace")
    session = _mock_session(user=target, clash=clash)
    _patch_session(mock_scope, session)
    with pytest.raises(ConflictError):
        AdminUserService.edit_profile(actor, "USR_9", {"username": "grace"})


@patch("app.admin.services.session_scope")
def test_edit_profile_requires_an_editable_field(mock_scope):
    actor = _user(id="ADM_1", is_admin=True)
    _patch_session(mock_scope, _mock_session(user=_user(id="USR_9")))
    with pytest.raises(ValidationError):
        AdminUserService.edit_profile(actor, "USR_9", {"email": "x@y.z"})


@patch("app.admin.services.session_scope")
def test_manage_roles_wont_enable_a_missing_seller_account(mock_scope):
    actor = _user(id="ADM_0", is_admin=True)
    target = _user(id="USR_9")  # no seller_account on a transient instance
    _patch_session(mock_scope, _mock_session(user=target))
    with pytest.raises(ValidationError):
        AdminUserService.manage_roles(actor, "USR_9", is_seller=True)


@patch("app.admin.services.read_scope")
def test_resend_verification_rejects_already_verified(mock_read):
    actor = _user(id="ADM_1", is_admin=True)
    target = _user(id="USR_9", email_verified=True)
    mock_read.return_value.__enter__.return_value = _mock_session(user=target)
    with pytest.raises(ValidationError):
        AdminUserService.resend_verification(actor, "USR_9")


# --- HTTP: permission gates -----------------------------------------------


@pytest.fixture
def client():
    flask_app, _socketio = create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _authed(**kwargs):
    user = MagicMock()
    user.is_authenticated = True
    for k, v in kwargs.items():
        setattr(user, k, v)
    return user


def test_admin_users_requires_auth(client):
    assert client.get("/api/v1/admin/users").status_code == 401


@patch("flask_login.utils._get_user")
def test_admin_users_forbidden_for_non_staff(mock_get_user, client):
    mock_get_user.return_value = _authed(is_admin=False, admin_role=None)
    assert client.get("/api/v1/admin/users").status_code == 403


@patch("flask_login.utils._get_user")
def test_support_cannot_ban_lacks_permission(mock_get_user, client):
    """Support holds user.view/edit but not user.ban -- gate must reject."""
    mock_get_user.return_value = _authed(is_admin=False, admin_role="support")
    resp = client.post("/api/v1/admin/users/USR_9/ban", json={"reason": "x"})
    assert resp.status_code == 403


@patch("app.admin.services.AdminUserService.list_users")
@patch("flask_login.utils._get_user")
def test_support_can_list_users(mock_get_user, mock_list, client):
    mock_get_user.return_value = _authed(is_admin=False, admin_role="support")
    mock_list.return_value = {
        "items": [],
        "page": 1,
        "per_page": 20,
        "total_items": 0,
        "total_pages": 0,
    }
    resp = client.get("/api/v1/admin/users")
    assert resp.status_code == 200
    mock_list.assert_called_once()
