"""Seller application review flow (#9).

The real gate: applying to sell creates the shop in verification_status=pending
WITHOUT activating it, and the account only becomes a seller when an admin
approves it. Contrast POST /users/create-seller, which activates instantly.

House style: session_scope is mocked rather than standing up a DB, and the
notification fan-out (which opens its own real session) is patched out. These
pin the behaviour that matters -- what gets set on the Seller/User, the guards,
and that approval activates the account.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import ConflictError
from app.users.models import Seller, SellerVerificationStatus, User
from app.users.services import AccountService
from app.admin.seller_services import AdminSellerService

# Where the services lazily import create_notification from -- patch target.
_NOTIFY = "app.notifications.services.NotificationService.create_notification"


def _data(**over):
    d = {
        "shop_name": "Ada's Wares",
        "description": "Fine goods",
        "category_ids": [],
        "documents": [{"type": "gov_id", "media_id": 1}],
    }
    d.update(over)
    return d


def _session(user, existing_seller=None, added=None):
    """A mock session where User.get -> user, Seller.filter_by().first() ->
    existing_seller, and session.add captures created rows into `added`."""
    session = MagicMock()

    def query(model):
        q = MagicMock()
        if model is User:
            q.get.return_value = user
        elif model is Seller:
            q.filter_by.return_value.first.return_value = existing_seller
            q.get.return_value = None
        else:  # Category etc.
            q.get.return_value = MagicMock()
        return q

    session.query.side_effect = query
    if added is not None:
        session.add.side_effect = added.append
    return session


# --- application (non-auto-activating) -----------------------------------


@patch(_NOTIFY)
@patch("app.users.services.session_scope")
def test_application_does_not_activate_and_is_pending(mock_scope, _notify):
    user = User(id="USR_1", email="ada@markt.co", is_seller=False)
    added = []
    mock_scope.return_value.__enter__.return_value = _session(
        user, existing_seller=None, added=added
    )

    result = AccountService.submit_seller_application("USR_1", _data())

    # The gate: the account is NOT activated by applying.
    assert user.is_seller is False
    # A Seller row was created, pending, carrying its documents.
    created = next(a for a in added if isinstance(a, Seller))
    assert created.verification_status is SellerVerificationStatus.PENDING
    assert created.verification_documents == [{"type": "gov_id", "media_id": 1}]
    assert result["verification_status"] is SellerVerificationStatus.PENDING


@patch("app.users.services.session_scope")
def test_existing_active_seller_cannot_apply(mock_scope):
    user = User(id="USR_1", email="ada@markt.co", is_seller=True)
    mock_scope.return_value.__enter__.return_value = _session(user)

    with pytest.raises(ConflictError):
        AccountService.submit_seller_application("USR_1", _data())


@patch("app.users.services.session_scope")
def test_application_already_under_review_is_rejected(mock_scope):
    user = User(id="USR_1", email="ada@markt.co", is_seller=False)
    pending = Seller(
        user_id="USR_1", verification_status=SellerVerificationStatus.PENDING
    )
    mock_scope.return_value.__enter__.return_value = _session(
        user, existing_seller=pending
    )

    with pytest.raises(ConflictError):
        AccountService.submit_seller_application("USR_1", _data())


@patch(_NOTIFY)
@patch("app.users.services.session_scope")
def test_reapplication_after_rejection_reopens_the_same_shop(mock_scope, _notify):
    user = User(id="USR_1", email="ada@markt.co", is_seller=False)
    rejected = Seller(
        id=7,
        user_id="USR_1",
        verification_status=SellerVerificationStatus.REJECTED,
        verification_note="blurry id",
    )
    added = []
    mock_scope.return_value.__enter__.return_value = _session(
        user, existing_seller=rejected, added=added
    )

    AccountService.submit_seller_application("USR_1", _data(shop_name="New Name"))

    # Reuses the row (no new Seller added), back to pending, reason cleared.
    assert not [a for a in added if isinstance(a, Seller)]
    assert rejected.verification_status is SellerVerificationStatus.PENDING
    assert rejected.verification_note is None
    assert rejected.shop_name == "New Name"
    assert user.is_seller is False


# --- admin decision activates / notifies ---------------------------------


def _admin_session(seller):
    session = MagicMock()
    session.query.return_value.get.return_value = seller
    return session


@patch(_NOTIFY)
@patch("app.admin.seller_services.session_scope")
def test_approval_activates_the_account(mock_scope, _notify):
    user = User(id="USR_1", email="ada@markt.co", is_seller=False)
    seller = Seller(
        id=1, user_id="USR_1", verification_status=SellerVerificationStatus.PENDING
    )
    seller.user = user
    mock_scope.return_value.__enter__.return_value = _admin_session(seller)
    actor = User(id="ADM_1", email="admin@markt.co", is_admin=True)

    AdminSellerService.verify_seller(actor, 1, note="docs checked")

    assert seller.verification_status is SellerVerificationStatus.VERIFIED
    assert user.is_seller is True
    _notify.assert_called_once()


@patch(_NOTIFY)
@patch("app.admin.seller_services.session_scope")
def test_rejection_notifies_applicant_with_reason(mock_scope, _notify):
    seller = Seller(
        id=1, user_id="USR_1", verification_status=SellerVerificationStatus.PENDING
    )
    mock_scope.return_value.__enter__.return_value = _admin_session(seller)
    actor = User(id="ADM_1", email="admin@markt.co", is_admin=True)

    AdminSellerService.reject_seller(actor, 1, reason="ID photo unreadable")

    assert seller.verification_status is SellerVerificationStatus.REJECTED
    assert seller.verification_note == "ID photo unreadable"
    _notify.assert_called_once()
