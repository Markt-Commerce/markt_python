"""Increment 3: §2 admin seller verification & shop management.

Service tests with mocked session scopes plus HTTP permission-gate tests.
Run in the Docker/CI env -- these import the full ORM stack.
"""

from unittest.mock import MagicMock, patch

import pytest

from main.setup import create_app

from app.admin.seller_services import AdminSellerService
from app.libs.errors import NotFoundError, ValidationError
from app.users.models import (
    MarketVerificationStatus,
    Seller,
    SellerVerificationStatus,
    User,
)


def _seller(**kwargs):
    defaults = dict(
        id=1,
        user_id="USR_1",
        shop_name="Ada's Wares",
        is_active=True,
        is_featured=False,
        verification_status=SellerVerificationStatus.PENDING,
        market_verification_status=MarketVerificationStatus.UNVERIFIED,
    )
    defaults.update(kwargs)
    return Seller(**defaults)


def _actor():
    return User(id="ADM_1", email="admin@markt.co", is_admin=True)


def _mock_session(seller=None):
    session = MagicMock()
    session.query.return_value.get.return_value = seller
    return session


def _patch(mock_scope, session):
    mock_scope.return_value.__enter__.return_value = session


# --- verification --------------------------------------------------------


@patch("app.admin.seller_services.session_scope")
def test_verify_sets_status_and_note_and_audits(mock_scope):
    seller = _seller()
    _patch(mock_scope, _mock_session(seller))
    result = AdminSellerService.verify_seller(_actor(), 1, "docs checked")
    assert seller.verification_status is SellerVerificationStatus.VERIFIED
    assert seller.verification_note == "docs checked"
    assert result["verification_status"] == "verified"


@patch("app.admin.seller_services.session_scope")
def test_reject_requires_a_reason(mock_scope):
    _patch(mock_scope, _mock_session(_seller()))
    with pytest.raises(ValidationError):
        AdminSellerService.reject_seller(_actor(), 1, "")


@patch("app.admin.seller_services.session_scope")
def test_reject_sets_status_and_stores_reason(mock_scope):
    seller = _seller()
    _patch(mock_scope, _mock_session(seller))
    result = AdminSellerService.reject_seller(_actor(), 1, "blurry ID")
    assert seller.verification_status is SellerVerificationStatus.REJECTED
    assert seller.verification_note == "blurry ID"
    assert result["verification_status"] == "rejected"


@patch("app.admin.seller_services.session_scope")
def test_missing_seller_is_404(mock_scope):
    _patch(mock_scope, _mock_session(None))
    with pytest.raises(NotFoundError):
        AdminSellerService.verify_seller(_actor(), 999)


# --- suspend keeps KYC, flips the real gate ------------------------------


@patch("app.admin.seller_services.session_scope")
def test_suspend_deactivates_but_preserves_verification(mock_scope):
    seller = _seller(verification_status=SellerVerificationStatus.VERIFIED)
    _patch(mock_scope, _mock_session(seller))
    result = AdminSellerService.suspend_seller(_actor(), 1, "chargebacks")
    assert seller.is_active is False
    # KYC standing survives the suspension.
    assert seller.verification_status is SellerVerificationStatus.VERIFIED
    assert result["is_active"] is False


@patch("app.admin.seller_services.session_scope")
def test_unsuspend_reactivates(mock_scope):
    seller = _seller(is_active=False)
    _patch(mock_scope, _mock_session(seller))
    result = AdminSellerService.unsuspend_seller(_actor(), 1)
    assert seller.is_active is True
    assert result["is_active"] is True


# --- market verification review ------------------------------------------


@patch("app.admin.seller_services.session_scope")
def test_market_review_sets_status(mock_scope):
    seller = _seller(market_verification_status=MarketVerificationStatus.FLAGGED)
    _patch(mock_scope, _mock_session(seller))
    result = AdminSellerService.review_market_verification(_actor(), 1, "verified")
    assert seller.market_verification_status is MarketVerificationStatus.VERIFIED
    assert result["market_verification_status"] == "verified"


@patch("app.admin.seller_services.session_scope")
def test_market_review_rejects_unknown_status(mock_scope):
    _patch(mock_scope, _mock_session(_seller()))
    with pytest.raises(ValidationError):
        AdminSellerService.review_market_verification(_actor(), 1, "sideways")


# --- payout & feature ----------------------------------------------------


@patch("app.admin.seller_services.session_scope")
def test_edit_payout_applies_only_payout_fields(mock_scope):
    seller = _seller()
    _patch(mock_scope, _mock_session(seller))
    result = AdminSellerService.edit_payout(
        _actor(),
        1,
        {
            "payout_bank_code": "058",
            "payout_account_number": "0123456789",
            "shop_name": "hacked",
        },  # non-payout field must be ignored
    )
    assert seller.payout_bank_code == "058"
    assert seller.payout_account_number == "0123456789"
    assert seller.shop_name == "Ada's Wares"  # untouched
    assert result["payout"]["bank_code"] == "058"


@patch("app.admin.seller_services.session_scope")
def test_edit_payout_requires_a_field(mock_scope):
    _patch(mock_scope, _mock_session(_seller()))
    with pytest.raises(ValidationError):
        AdminSellerService.edit_payout(_actor(), 1, {"nope": "x"})


@patch("app.admin.seller_services.session_scope")
def test_feature_and_unfeature(mock_scope):
    seller = _seller()
    _patch(mock_scope, _mock_session(seller))
    assert AdminSellerService.set_featured(_actor(), 1, True)["is_featured"] is True
    assert seller.is_featured is True
    assert AdminSellerService.set_featured(_actor(), 1, False)["is_featured"] is False
    assert seller.is_featured is False


# --- HTTP permission gates -----------------------------------------------


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


def test_sellers_requires_auth(client):
    assert client.get("/api/v1/admin/sellers").status_code == 401


@patch("flask_login.utils._get_user")
def test_finance_cannot_verify_but_catalog_permission_split(mock_get_user, client):
    """Finance holds seller.edit_payout, not seller.verify."""
    mock_get_user.return_value = _authed(is_admin=False, admin_role="finance")
    resp = client.post("/api/v1/admin/sellers/1/verify", json={})
    assert resp.status_code == 403


@patch("flask_login.utils._get_user")
def test_catalog_cannot_edit_payout(mock_get_user, client):
    """Catalog can verify/suspend/feature but not touch payout (finance-only)."""
    mock_get_user.return_value = _authed(is_admin=False, admin_role="catalog")
    resp = client.patch(
        "/api/v1/admin/sellers/1/payout", json={"payout_bank_code": "058"}
    )
    assert resp.status_code == 403


@patch("app.admin.seller_services.AdminSellerService.list_sellers")
@patch("flask_login.utils._get_user")
def test_catalog_can_list_sellers(mock_get_user, mock_list, client):
    mock_get_user.return_value = _authed(is_admin=False, admin_role="catalog")
    mock_list.return_value = {
        "items": [],
        "page": 1,
        "per_page": 20,
        "total_items": 0,
        "total_pages": 0,
    }
    resp = client.get("/api/v1/admin/sellers?verification_status=pending")
    assert resp.status_code == 200
    mock_list.assert_called_once()
