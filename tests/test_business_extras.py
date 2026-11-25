"""Markt Business, second pass: admin verification, verification requests,
business orders, plan checkout through Paystack, and logo/cover uploads.

Service tests with mocked session scopes plus HTTP permission gates, in the
same style as test_admin_sellers.py and test_business.py.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import marshmallow
import pytest

from main.config import settings
from main.setup import create_app

from app.admin.business_services import AdminBusinessService
from app.admin.permissions import AdminRole, Permission, ROLE_PERMISSIONS
from app.business.models import (
    BusinessProfile,
    BusinessSubscription,
    BusinessSubscriptionPlan,
    BusinessSubscriptionStatus,
    BusinessVerificationStatus,
)
from app.business.orders import stamp_business_order
from app.business.schemas import BusinessProfileUpsertSchema
from app.business.services import BusinessService
from app.business import subscription_checkout as checkout
from app.libs.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.orders.models import Order
from app.orders.schemas import BuyerOrderSchema, OrderSimpleSchema
from app.users.models import Buyer, User


def _patch(mock_scope, session):
    mock_scope.return_value.__enter__.return_value = session


def _user(**kwargs):
    defaults = dict(
        id="USR_1",
        email="ada@markt.co",
        username="ada",
        is_business=True,
        is_buyer=True,
    )
    defaults.update(kwargs)
    return User(**defaults)


def _profile(status=BusinessVerificationStatus.UNVERIFIED):
    profile = BusinessProfile(
        user_id="USR_1",
        name="Ada Farms",
        business_types=["producer"],
        verification_status=status,
    )
    profile.user = _user()
    return profile


@pytest.fixture
def client():
    flask_app, _socketio = create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def subscriptions_on():
    with patch.object(settings, "BUSINESS_SUBSCRIPTIONS_ENABLED", True):
        yield


def _authed(**kwargs):
    user = MagicMock()
    user.is_authenticated = True
    for k, v in kwargs.items():
        setattr(user, k, v)
    return user


# --- admin verification ----------------------------------------------------


def _admin_session(profile):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = profile
    return session


@patch("app.admin.business_services.AdminAuditService")
@patch("app.admin.business_services.session_scope")
def test_admin_verify_sets_status_and_audits(mock_scope, mock_audit):
    profile = _profile(BusinessVerificationStatus.PENDING)
    _patch(mock_scope, _admin_session(profile))

    result = AdminBusinessService.verify_business(
        MagicMock(id="ADM_1"), "USR_1", "CAC checked"
    )

    assert profile.verification_status is BusinessVerificationStatus.VERIFIED
    assert profile.verification_note == "CAC checked"
    assert result["verification_status"] == "verified"
    args, kwargs = mock_audit.record.call_args
    assert args[2] == "business.verify"
    assert kwargs["before"] == {"verification_status": "pending"}


@patch("app.admin.business_services.session_scope")
def test_admin_reject_requires_a_reason(mock_scope):
    _patch(mock_scope, _admin_session(_profile()))
    with pytest.raises(ValidationError):
        AdminBusinessService.reject_business(MagicMock(), "USR_1", "")


@patch("app.admin.business_services.session_scope")
def test_admin_missing_business_is_404(mock_scope):
    _patch(mock_scope, _admin_session(None))
    with pytest.raises(NotFoundError):
        AdminBusinessService.verify_business(MagicMock(), "USR_X")


def test_permission_split_matches_sellers():
    assert Permission.BUSINESS_VERIFY in ROLE_PERMISSIONS[AdminRole.CATALOG]
    assert Permission.BUSINESS_VIEW in ROLE_PERMISSIONS[AdminRole.SUPPORT]
    assert Permission.BUSINESS_VERIFY not in ROLE_PERMISSIONS[AdminRole.SUPPORT]


def test_admin_businesses_requires_auth(client):
    assert client.get("/api/v1/admin/businesses").status_code == 401


@patch("flask_login.utils._get_user")
def test_support_cannot_verify_a_business(mock_get_user, client):
    mock_get_user.return_value = _authed(is_admin=False, admin_role="support")
    assert (
        client.post("/api/v1/admin/businesses/USR_1/verify", json={}).status_code == 403
    )


# --- verification requests from the business -----------------------------


def _user_with_profile(status):
    user = _user()
    user.business_profile = BusinessProfile(
        name="Ada", business_types=["producer"], verification_status=status
    )
    return user


@patch("app.business.services.session_scope")
def test_verification_request_needs_the_flag(mock_scope):
    with pytest.raises(ForbiddenError):
        BusinessService.request_verification("USR_1")


@patch("app.business.services.session_scope")
def test_verification_request_moves_to_pending(mock_scope):
    user = _user_with_profile(BusinessVerificationStatus.REJECTED)
    session = MagicMock()
    session.query.return_value.get.return_value = user
    _patch(mock_scope, session)
    with patch.object(settings, "BUSINESS_VERIFICATION_ENABLED", True):
        BusinessService.request_verification("USR_1")
    assert (
        user.business_profile.verification_status is BusinessVerificationStatus.PENDING
    )


@patch("app.business.services.session_scope")
def test_verified_business_cannot_request_again(mock_scope):
    session = MagicMock()
    session.query.return_value.get.return_value = _user_with_profile(
        BusinessVerificationStatus.VERIFIED
    )
    _patch(mock_scope, session)
    with patch.object(settings, "BUSINESS_VERIFICATION_ENABLED", True):
        with pytest.raises(ConflictError):
            BusinessService.request_verification("USR_1")


# --- business orders --------------------------------------------------------


def _buyer_session(user):
    buyer = Buyer(id=7, user_id=user.id)
    buyer.user = user
    session = MagicMock()
    session.query.return_value.get.return_value = buyer
    return session


def test_business_buyer_order_is_stamped():
    order = Order()
    stamp_business_order(_buyer_session(_user(is_business=True)), order, 7)
    assert order.is_business is True


def test_consumer_order_is_not():
    order = Order()
    stamp_business_order(_buyer_session(_user(is_business=False)), order, 7)
    assert order.is_business is False


@patch("app.business.entitlements.db")
def test_lapsed_subscription_order_is_not_business(mock_db, subscriptions_on):
    mock_db.session.query.return_value.scalar.return_value = False
    order = Order()
    stamp_business_order(_buyer_session(_user(is_business=True)), order, 7)
    assert order.is_business is False


def test_order_payloads_carry_the_flag():
    order = Order(id="ORD_1", order_number="MKT-1", is_business=True)
    assert BuyerOrderSchema().dump(order)["is_business"] is True
    assert OrderSimpleSchema().dump(order)["is_business"] is True


# --- plan checkout ----------------------------------------------------------


def test_period_end():
    start = datetime(2026, 1, 1)
    assert checkout.period_end(start, "monthly") == start + timedelta(days=30)
    assert checkout.period_end(start, "yearly") == start + timedelta(days=365)
    assert checkout.period_end(start, "fortnightly") == start + timedelta(days=30)


def test_checkout_404_while_subscriptions_are_off():
    with pytest.raises(NotFoundError):
        checkout.start_checkout("USR_1", 1)


def _plan(price=5000):
    return BusinessSubscriptionPlan(
        id=1,
        key="starter",
        name="Starter",
        price=price,
        currency="NGN",
        billing_interval="monthly",
        is_active=True,
    )


def _checkout_session(user, plan):
    session = MagicMock()
    session.query.return_value.get.side_effect = [user, plan]
    session.query.return_value.filter.return_value.all.return_value = []

    def add(obj):
        obj.id = 42

    session.add.side_effect = add
    return session


@patch("app.business.subscription_checkout.requests")
@patch("app.business.subscription_checkout.session_scope")
def test_free_plan_activates_without_paystack(
    mock_scope, mock_requests, subscriptions_on
):
    user = _user()
    user.business_profile = BusinessProfile(name="Ada", business_types=["producer"])
    _patch(mock_scope, _checkout_session(user, _plan(price=0)))

    result = checkout.start_checkout("USR_1", 1)

    assert result["status"] == "ACTIVE"
    assert result["authorization_url"] is None
    mock_requests.post.assert_not_called()


@patch("app.business.subscription_checkout.requests")
@patch("app.business.subscription_checkout.session_scope")
def test_paid_plan_returns_paystack_url(mock_scope, mock_requests, subscriptions_on):
    user = _user()
    user.business_profile = BusinessProfile(name="Ada", business_types=["producer"])
    _patch(mock_scope, _checkout_session(user, _plan()))
    mock_requests.post.return_value.status_code = 200
    mock_requests.post.return_value.json.return_value = {
        "status": True,
        "data": {
            "authorization_url": "https://checkout.paystack.com/x",
            "reference": "SUB_42",
        },
    }

    result = checkout.start_checkout("USR_1", 1, "mobile")

    assert result == {
        "subscription_id": 42,
        "status": "PENDING",
        "authorization_url": "https://checkout.paystack.com/x",
        "reference": "SUB_42",
    }
    payload = mock_requests.post.call_args.kwargs["json"]
    assert payload["amount"] == 500000  # kobo
    assert payload["reference"] == "SUB_42"
    assert payload["metadata"]["type"] == "business_subscription"
    assert payload["callback_url"].endswith(
        "/subscriptions/callback/42?platform=mobile"
    )


@patch("app.business.subscription_checkout.session_scope")
def test_checkout_needs_a_business(mock_scope, subscriptions_on):
    _patch(mock_scope, _checkout_session(_user(is_business=False), _plan()))
    with pytest.raises(ForbiddenError):
        checkout.start_checkout("USR_1", 1)


def _pending_subscription(plan):
    sub = BusinessSubscription(
        id=42,
        user_id="USR_1",
        plan_id=1,
        status=BusinessSubscriptionStatus.PENDING,
        payment_reference="SUB_42",
    )
    sub.plan = plan
    return sub


def _complete_session(sub):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = sub
    session.query.return_value.filter.return_value.all.return_value = []
    return session


@patch("app.business.subscription_checkout.session_scope")
def test_payment_activates_for_one_period(mock_scope):
    sub = _pending_subscription(_plan())
    _patch(mock_scope, _complete_session(sub))

    assert checkout.complete_subscription(
        "SUB_42", {"status": "success", "amount": 500000, "currency": "NGN"}
    )
    assert sub.status is BusinessSubscriptionStatus.ACTIVE
    assert sub.end_date - sub.start_date == timedelta(days=30)


@patch("app.business.subscription_checkout.session_scope")
def test_wrong_amount_does_not_activate(mock_scope):
    sub = _pending_subscription(_plan())
    _patch(mock_scope, _complete_session(sub))

    assert not checkout.complete_subscription(
        "SUB_42", {"status": "success", "amount": 100, "currency": "NGN"}
    )
    assert sub.status is BusinessSubscriptionStatus.PENDING


@patch("app.business.subscription_checkout.session_scope")
def test_completion_is_idempotent(mock_scope):
    sub = _pending_subscription(_plan())
    sub.status = BusinessSubscriptionStatus.ACTIVE
    sub.end_date = datetime(2030, 1, 1)
    _patch(mock_scope, _complete_session(sub))

    assert checkout.complete_subscription(
        "SUB_42", {"status": "success", "amount": 500000}
    )
    assert sub.end_date == datetime(2030, 1, 1)  # not extended by a replay


@patch("app.business.subscription_checkout.complete_subscription", return_value=True)
def test_webhook_routes_plan_payments(mock_complete):
    from app.payments.services import PaymentService

    data = {"reference": "SUB_42", "status": "success", "amount": 500000}
    assert PaymentService._handle_successful_charge(data) is True
    mock_complete.assert_called_once_with("SUB_42", data)


# --- logo and cover ---------------------------------------------------------


def test_profile_no_longer_accepts_image_urls():
    with pytest.raises(marshmallow.ValidationError):
        BusinessProfileUpsertSchema().load(
            {
                "name": "Ada Farms",
                "business_types": ["producer"],
                "logo_url": "https://evil.example/x.png",
            }
        )


def test_logo_upload_requires_auth(client):
    assert client.post("/api/v1/business/me/logo").status_code == 401


def test_unknown_image_kind_is_404(client):
    assert client.post("/api/v1/business/me/banner").status_code in (401, 404)


@patch("app.business.subscription_checkout.session_scope")
def test_early_renewal_keeps_the_time_already_paid_for(mock_scope):
    plan = _plan()
    current = BusinessSubscription(
        id=41,
        user_id="USR_1",
        plan_id=1,
        status=BusinessSubscriptionStatus.ACTIVE,
        end_date=datetime.utcnow() + timedelta(days=10),
    )
    paid_until = current.end_date
    sub = _pending_subscription(plan)
    session = _complete_session(sub)
    session.query.return_value.filter.return_value.all.return_value = [current]
    _patch(mock_scope, session)

    assert checkout.complete_subscription(
        "SUB_42", {"status": "success", "amount": 500000}
    )
    assert sub.end_date == paid_until + timedelta(days=30)
    assert current.status is BusinessSubscriptionStatus.CANCELLED


@patch("app.business.subscription_checkout.session_scope")
def test_switching_plan_starts_from_now(mock_scope):
    other_plan_sub = BusinessSubscription(
        id=40,
        user_id="USR_1",
        plan_id=2,
        status=BusinessSubscriptionStatus.ACTIVE,
        end_date=datetime.utcnow() + timedelta(days=10),
    )
    sub = _pending_subscription(_plan())
    session = _complete_session(sub)
    session.query.return_value.filter.return_value.all.return_value = [other_plan_sub]
    _patch(mock_scope, session)

    assert checkout.complete_subscription(
        "SUB_42", {"status": "success", "amount": 500000}
    )
    assert sub.end_date - sub.start_date == timedelta(days=30)


def test_order_list_still_accepts_old_query_params():
    """The mobile app sends ?page=&per_page= to /orders/; adding the
    is_business filter must not start rejecting that."""
    from app.orders.schemas import OrderListQueryArgs

    assert OrderListQueryArgs().load({"page": "1", "per_page": "10"}) == {}
    assert OrderListQueryArgs().load({"is_business": "true"}) == {"is_business": True}
