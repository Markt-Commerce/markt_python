"""Increment 1 foundations: RBAC matrix, staff gate, audit recorder, /admin/me.

Unit-level for the permission/audit logic (no DB), plus a Flask-client smoke
test for the /admin/me gate mirroring tests/test_api_smoke.py's approach.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from main.setup import create_app

from app.admin.permissions import (
    AdminRole,
    Permission,
    all_permissions,
    has_permission,
    is_staff,
    is_super_admin,
    permissions_for,
)
from app.admin.services import AdminAuditService
from app.libs.decorators import _has_permission


def _user(is_admin=False, admin_role=None):
    return SimpleNamespace(
        id="USR_1",
        email="a@b.co",
        is_admin=is_admin,
        admin_role=admin_role,
        is_seller=False,
        is_buyer=False,
    )


# --- permission matrix ---------------------------------------------------


def test_is_admin_holds_every_permission():
    user = _user(is_admin=True)
    assert is_super_admin(user) is True
    assert permissions_for(user) == all_permissions()
    assert has_permission(user, Permission.SELLER_VERIFY) is True


def test_super_admin_role_holds_every_permission():
    user = _user(admin_role="super_admin")
    assert is_super_admin(user) is True
    assert permissions_for(user) == all_permissions()


def test_finance_role_is_scoped_to_its_grants():
    user = _user(admin_role="finance")
    assert is_super_admin(user) is False
    assert is_staff(user) is True
    assert has_permission(user, Permission.SELLER_EDIT_PAYOUT) is True
    # Finance cannot verify sellers or ban users.
    assert has_permission(user, Permission.SELLER_VERIFY) is False
    assert has_permission(user, Permission.USER_BAN) is False


def test_catalog_role_can_verify_but_not_touch_payouts():
    user = _user(admin_role="catalog")
    assert has_permission(user, Permission.SELLER_VERIFY) is True
    assert has_permission(user, Permission.SELLER_EDIT_PAYOUT) is False


def test_non_staff_holds_nothing():
    user = _user()
    assert is_staff(user) is False
    assert permissions_for(user) == set()
    assert has_permission(user, Permission.USER_VIEW) is False


def test_unknown_role_fails_closed():
    """A role string that maps to nothing grants nothing, rather than erroring."""
    user = _user(admin_role="wizard")
    assert is_staff(user) is False
    assert permissions_for(user) == set()


def test_every_role_grant_is_a_real_permission():
    """Guard against a typo'd permission string sitting in the matrix."""
    from app.admin.permissions import ROLE_PERMISSIONS

    valid = all_permissions()
    for role, perms in ROLE_PERMISSIONS.items():
        assert perms <= valid, f"{role} references unknown permission(s)"


# --- legacy permission fallback ------------------------------------------


def test_has_permission_delegates_admin_perms_to_matrix():
    finance = _user(admin_role="finance")
    assert _has_permission(finance, Permission.SELLER_EDIT_PAYOUT) is True
    assert _has_permission(finance, Permission.SELLER_VERIFY) is False


def test_has_permission_preserves_legacy_seller_permissions():
    """A seller (no admin standing) must still pass the legacy product perms."""
    seller = SimpleNamespace(
        is_admin=False, admin_role=None, is_seller=True, is_buyer=False
    )
    assert _has_permission(seller, "product.create") is True
    # ...but gains no admin capability from it.
    assert _has_permission(seller, Permission.SELLER_VERIFY) is False


# --- audit recorder ------------------------------------------------------


def test_audit_record_builds_row_on_the_given_session():
    session = MagicMock()
    actor = _user(admin_role="catalog")

    entry = AdminAuditService.record(
        session,
        actor,
        Permission.SELLER_VERIFY,
        target_type="seller",
        target_id=42,  # int PK must be coerced to str
        reason="docs checked out",
        before={"verification_status": "pending"},
        after={"verification_status": "verified"},
        ip_address="1.2.3.4",
    )

    session.add.assert_called_once_with(entry)
    assert entry.actor_id == "USR_1"
    assert entry.actor_role == "catalog"
    assert entry.action == Permission.SELLER_VERIFY
    assert entry.target_type == "seller"
    assert entry.target_id == "42"
    assert entry.before == {"verification_status": "pending"}
    assert entry.after == {"verification_status": "verified"}
    assert entry.ip_address == "1.2.3.4"


def test_audit_record_captures_no_role_for_bare_is_admin():
    session = MagicMock()
    actor = _user(is_admin=True)
    entry = AdminAuditService.record(session, actor, Permission.USER_BAN)
    # is_admin is not an AdminRole, so actor_role is null (the flag, not a role).
    assert entry.actor_role is None
    assert entry.target_id is None


# --- /admin/me gate (HTTP smoke) -----------------------------------------


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


@patch("flask_login.utils._get_user")
def test_admin_me_returns_role_and_permissions(mock_get_user, client):
    mock_get_user.return_value = _authed(
        id="USR_9", email="staff@markt.co", is_admin=False, admin_role="finance"
    )
    resp = client.get("/api/v1/admin/me")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["admin_role"] == "finance"
    assert body["is_super_admin"] is False
    assert Permission.SELLER_EDIT_PAYOUT in body["permissions"]
    assert Permission.SELLER_VERIFY not in body["permissions"]


@patch("flask_login.utils._get_user")
def test_admin_me_forbidden_for_non_staff(mock_get_user, client):
    mock_get_user.return_value = _authed(
        id="USR_2", email="buyer@markt.co", is_admin=False, admin_role=None
    )
    resp = client.get("/api/v1/admin/me")
    assert resp.status_code == 403


def test_admin_me_requires_auth(client):
    assert client.get("/api/v1/admin/me").status_code == 401
