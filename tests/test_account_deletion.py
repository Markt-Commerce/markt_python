"""Unit tests for in-app account deletion (Apple App Store 5.1.1(v)).

Deletion has to destroy everything personal while leaving other people's
records standing, and it must never fire while the user still holds money or
open obligations. These cover both halves.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import AuthError, ConflictError
from app.users.services import AccountDeletionService


def _user(**overrides):
    user = SimpleNamespace(
        id="USR_ABC123",
        email="ada@example.com",
        username="ada",
        phone_number="+2348000000000",
        profile_picture="ada.jpg",
        password_hash="hashed",
        email_verified=True,
        is_active=True,
        deactivated_at=None,
        deleted_at=None,
        buyer_account=None,
        seller_account=None,
    )
    user.check_password = lambda password: password == "correct-horse"
    for key, value in overrides.items():
        setattr(user, key, value)
    return user


def _session_for(user):
    session = MagicMock()
    session.query.return_value.get.return_value = user
    return session


def test_delete_account_rejects_wrong_password():
    """A 30-day bearer token off an unattended device must not be enough."""
    user = _user()
    session = _session_for(user)

    with patch.object(AccountDeletionService, "check_blockers", return_value=[]):
        with patch("app.users.services.session_scope") as scope:
            scope.return_value.__enter__.return_value = session
            with pytest.raises(AuthError):
                AccountDeletionService.delete_account("USR_ABC123", "wrong")

    assert user.deleted_at is None
    assert user.password_hash == "hashed"


def test_delete_account_refuses_while_blocked():
    blockers = [
        {
            "code": "wallet_balance",
            "message": "You still have NGN 2,500.00 in your wallet.",
            "detail": {"currency": "NGN", "available_balance": 2500.0},
        }
    ]
    with patch.object(AccountDeletionService, "check_blockers", return_value=blockers):
        with pytest.raises(ConflictError) as exc:
            AccountDeletionService.delete_account("USR_ABC123", "correct-horse")

    # The blockers ride along so the client can explain what to fix.
    assert exc.value.payload["blockers"] == blockers


def test_delete_account_anonymizes_personal_fields():
    user = _user()
    session = _session_for(user)

    with patch.object(AccountDeletionService, "check_blockers", return_value=[]):
        with patch("app.users.services.session_scope") as scope:
            scope.return_value.__enter__.return_value = session
            with patch(
                "app.users.services.UserService._clear_cached_current_role"
            ):
                result = AccountDeletionService.delete_account(
                    "USR_ABC123", "correct-horse"
                )

    assert result["deleted"] is True
    assert user.deleted_at is not None
    assert user.is_active is False
    # No path back into the account: the credential is destroyed, not rotated.
    assert user.password_hash is None
    # Identifiers are replaced with derived, non-personal values that still
    # satisfy the unique constraints on email and username.
    assert user.email == "deleted-abc123@deleted.markt.invalid"
    assert user.username == "deleted_user_abc123"
    assert user.phone_number is None
    assert user.profile_picture == "default.jpg"
    assert user.email_verified is False


def test_delete_account_scrubs_seller_payout_details():
    """Bank details are the most sensitive data on the account."""
    seller = SimpleNamespace(
        id=7,
        payout_bank_code="058",
        payout_account_number="0123456789",
        payout_account_name="Ada Lovelace",
        paystack_subaccount_code="ACCT_xyz",
        shop_address={"street": "12 Broad Street"},
        shop_latitude=6.45,
        shop_longitude=3.39,
        shop_name="Ada's Shop",
        shop_slug="adas-shop",
        description="Handmade",
        is_active=True,
        deactivated_at=None,
    )
    user = _user(seller_account=seller)
    session = _session_for(user)

    with patch.object(AccountDeletionService, "check_blockers", return_value=[]):
        with patch("app.users.services.session_scope") as scope:
            scope.return_value.__enter__.return_value = session
            with patch(
                "app.users.services.UserService._clear_cached_current_role"
            ):
                AccountDeletionService.delete_account("USR_ABC123", "correct-horse")

    assert seller.payout_bank_code is None
    assert seller.payout_account_number is None
    assert seller.payout_account_name is None
    assert seller.paystack_subaccount_code is None
    assert seller.shop_address is None
    assert seller.shop_latitude is None
    assert seller.shop_longitude is None
    assert seller.is_active is False
    assert "Ada" not in seller.shop_name


def test_delete_account_is_not_repeatable():
    user = _user(deleted_at="2026-09-01T00:00:00")
    session = _session_for(user)

    with patch.object(AccountDeletionService, "check_blockers", return_value=[]):
        with patch("app.users.services.session_scope") as scope:
            scope.return_value.__enter__.return_value = session
            with pytest.raises(ConflictError):
                AccountDeletionService.delete_account("USR_ABC123", "correct-horse")


def test_check_password_is_false_for_destroyed_hash():
    """Deletion nulls the hash, and passlib raises rather than returning False
    on a null hash -- which would surface as a 500 on the login route."""
    from app.users.models import User

    user = User()
    user.password_hash = None
    assert user.check_password("anything") is False
