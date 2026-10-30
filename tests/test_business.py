"""Markt Business foundation: feature config, the is_business tag and its
entitlement rule, profiles, B2B listings, procurement on buyer requests.

Service tests with mocked session scopes, plus HTTP tests for the endpoints
that need no database. The critical property throughout: with subscriptions
disabled, nothing is ever blocked for want of a subscription.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import marshmallow
import pytest

from main.config import settings
from main.setup import create_app

from app.business.entitlements import EntitlementService
from app.business.features import business_config, business_features
from app.business.schemas import (
    BusinessListingUpsertSchema,
    BusinessProfileUpsertSchema,
    BusinessPublicProfileSchema,
)
from app.business.services import (
    BusinessListingService,
    BusinessService,
    BusinessSubscriptionService,
)
from app.business.models import BusinessProfile
from app.libs.errors import ForbiddenError, NotFoundError
from app.requests.models import BuyerRequest, RequestStatus
from app.requests.schemas import BuyerRequestCreateSchema
from app.requests.services import BuyerRequestService
from app.users.models import Seller, User
from app.users.schemas import UserSchema


@pytest.fixture
def subscriptions_on():
    with patch.object(settings, "BUSINESS_SUBSCRIPTIONS_ENABLED", True):
        yield


def _user(**kwargs):
    defaults = dict(
        id="USR_1",
        email="ada@markt.co",
        username="ada",
        is_buyer=True,
        is_seller=True,
        is_business=False,
        is_active=True,
    )
    defaults.update(kwargs)
    return User(**defaults)


def _patch(mock_scope, session):
    mock_scope.return_value.__enter__.return_value = session


def _session_returning(obj):
    session = MagicMock()
    session.query.return_value.get.return_value = obj
    return session


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app = app[0] if isinstance(app, tuple) else app
    app.config["TESTING"] = True
    return app.test_client()


# --- feature config --------------------------------------------------------


def test_defaults_enable_business_and_disable_subscriptions():
    features = business_features()
    assert features["enabled"] is True
    assert features["registration_enabled"] is True
    assert features["discovery_enabled"] is True
    assert features["procurement_enabled"] is True
    assert features["subscriptions_enabled"] is False


def test_business_mode_off_turns_every_business_feature_off():
    with patch.object(settings, "BUSINESS_MODE_ENABLED", False), patch.object(
        settings, "BUSINESS_SUBSCRIPTIONS_ENABLED", True
    ):
        assert not any(business_features().values())


def test_config_carries_lookup_lists():
    config = business_config()
    assert {"key": "tonne", "label": "Tonnes"} in config["units"]
    assert any(t["key"] == "producer" for t in config["business_types"])


def test_config_endpoint_is_public(client):
    response = client.get("/api/v1/business/config")
    assert response.status_code == 200
    assert response.get_json()["features"]["subscriptions_enabled"] is False


# --- entitlement -----------------------------------------------------------


def test_untagged_user_is_never_business():
    assert EntitlementService.is_business(_user(is_business=False)) is False
    assert EntitlementService.is_business(None) is False


@patch("app.business.entitlements.db")
def test_tag_alone_counts_while_subscriptions_are_off(mock_db):
    assert EntitlementService.is_business(_user(is_business=True)) is True
    # No subscription lookup at all: nothing can be blocked by one.
    mock_db.session.query.assert_not_called()


@patch("app.business.entitlements.db")
def test_tag_needs_a_subscription_once_subscriptions_are_on(mock_db, subscriptions_on):
    mock_db.session.query.return_value.scalar.return_value = False
    assert EntitlementService.is_business(_user(is_business=True)) is False
    mock_db.session.query.return_value.scalar.return_value = True
    assert EntitlementService.is_business(_user(is_business=True)) is True


def test_has_feature_is_unconditional_while_subscriptions_are_off():
    assert EntitlementService.has_feature("USR_1", "anything") is True


def test_list_filter_is_just_the_tag_while_subscriptions_are_off():
    sql = str(EntitlementService.business_user_filter(User))
    assert "is_business" in sql
    assert "business_subscriptions" not in sql


def test_list_filter_checks_subscriptions_once_on(subscriptions_on):
    sql = str(EntitlementService.business_user_filter(User))
    assert "business_subscriptions" in sql


def test_user_payload_reports_effective_business_status():
    assert UserSchema().dump(_user(is_business=True))["is_business"] is True
    assert UserSchema().dump(_user(is_business=False))["is_business"] is False


# --- subscriptions stay hidden while disabled ------------------------------


def test_subscription_reads_are_not_found_while_disabled():
    with pytest.raises(NotFoundError):
        BusinessSubscriptionService.list_plans()
    with pytest.raises(NotFoundError):
        BusinessSubscriptionService.current_subscription("USR_1")


def test_plans_endpoint_is_404_while_disabled(client):
    assert client.get("/api/v1/business/subscriptions/plans").status_code == 404


# --- profile ---------------------------------------------------------------


def _profile_payload(**kwargs):
    data = dict(name="Ada Cassava Farms", business_types=["producer"])
    data.update(kwargs)
    return data


def test_profile_rejects_unknown_business_type():
    with pytest.raises(marshmallow.ValidationError):
        BusinessProfileUpsertSchema().load(_profile_payload(business_types=["wizard"]))


def test_profile_cannot_set_its_own_verification_status():
    with pytest.raises(marshmallow.ValidationError):
        BusinessProfileUpsertSchema().load(
            _profile_payload(verification_status="VERIFIED")
        )


def test_public_profile_hides_registration_number():
    profile = BusinessProfile(
        user_id="USR_1",
        name="Ada",
        business_types=["producer"],
        registration_number="RC123456",
    )
    profile.user = _user()
    dumped = BusinessPublicProfileSchema().dump(profile)
    assert "registration_number" not in dumped
    assert dumped["buys"] is True and dumped["sells"] is True


@patch("app.business.services.session_scope")
def test_saving_a_profile_sets_the_tag(mock_scope):
    user = _user(is_business=False)
    _patch(mock_scope, _session_returning(user))
    data = BusinessProfileUpsertSchema().load(_profile_payload())

    result = BusinessService.upsert_profile("USR_1", data)

    assert user.is_business is True
    assert user.business_profile.name == "Ada Cassava Farms"
    assert result["is_business"] is True
    assert result["requires_subscription"] is False


@patch("app.business.entitlements.db")
@patch("app.business.services.session_scope")
def test_tag_without_subscription_reports_requires_subscription(
    mock_scope, mock_db, subscriptions_on
):
    mock_db.session.query.return_value.scalar.return_value = False
    user = _user(is_business=True)
    _patch(mock_scope, _session_returning(user))

    result = BusinessService.my_business("USR_1")

    assert result["is_business"] is False
    assert result["business_tag"] is True
    assert result["requires_subscription"] is True


@patch("app.business.services.session_scope")
def test_registration_flag_off_blocks_new_profiles(mock_scope):
    with patch.object(settings, "BUSINESS_REGISTRATION_ENABLED", False):
        with pytest.raises(ForbiddenError):
            BusinessService.upsert_profile("USR_1", _profile_payload())


@patch("app.business.services.session_scope")
def test_non_business_profile_is_not_found(mock_scope):
    _patch(mock_scope, _session_returning(_user(is_business=False)))
    with pytest.raises(NotFoundError):
        BusinessService.get_public_profile("USR_1")


# --- B2B listings ----------------------------------------------------------


def test_listing_rejects_unknown_unit():
    with pytest.raises(marshmallow.ValidationError):
        BusinessListingUpsertSchema().load({"unit": "furlong"})


def _product(owner_user_id="USR_1"):
    product = MagicMock()
    product.id = "PRD_1"
    product.status = None
    product.seller = Seller(id=1, user_id=owner_user_id)
    product.business_listing = None
    return product


def _listing_session(user, product):
    session = MagicMock()
    session.query.return_value.get.side_effect = [user, product]
    return session


@patch("app.business.services.session_scope")
def test_listing_requires_a_business_account(mock_scope):
    _patch(mock_scope, _listing_session(_user(is_business=False), _product()))
    with pytest.raises(ForbiddenError):
        BusinessListingService.upsert_listing("USR_1", "PRD_1", {"unit": "kg"})


@patch("app.business.services.session_scope")
def test_listing_only_on_own_product(mock_scope):
    _patch(
        mock_scope,
        _listing_session(_user(is_business=True), _product(owner_user_id="USR_2")),
    )
    with pytest.raises(ForbiddenError):
        BusinessListingService.upsert_listing("USR_1", "PRD_1", {"unit": "kg"})


@patch("app.business.services.session_scope")
def test_listing_defaults_location_from_profile(mock_scope):
    user = _user(is_business=True)
    user.business_profile = BusinessProfile(
        name="Ada", business_types=["producer"], city="Ibadan", state="Oyo"
    )
    _patch(mock_scope, _listing_session(user, _product()))

    listing = BusinessListingService.upsert_listing(
        "USR_1", "PRD_1", {"unit": "tonne", "available_quantity": 2.5}
    )

    assert listing.unit == "tonne"
    assert listing.available_quantity == 2.5
    assert (listing.city, listing.state) == ("Ibadan", "Oyo")


# --- procurement on buyer requests -----------------------------------------


def test_request_schema_accepts_procurement_fields():
    data = BuyerRequestCreateSchema().load(
        {
            "title": "Cassava, 20 tonnes monthly",
            "description": "Fresh cassava roots for garri production.",
            "quantity": 20,
            "unit": "tonne",
            "specifications": {"variety": "TME 419"},
            "delivery_location": "Ibadan, Oyo",
            "required_delivery_date": "2026-12-01",
        }
    )
    assert data["unit"] == "tonne"
    assert data["required_delivery_date"] == date(2026, 12, 1)


def test_request_schema_rejects_unknown_unit():
    with pytest.raises(marshmallow.ValidationError):
        BuyerRequestCreateSchema().load(
            {"title": "x", "description": "long enough text", "unit": "furlong"}
        )


@pytest.mark.parametrize("tagged", [True, False])
@patch.object(BuyerRequestService, "_notify_relevant_sellers")
@patch.object(BuyerRequestService, "_invalidate_user_cache")
@patch("app.requests.services.session_scope")
def test_request_is_stamped_with_business_status(mock_scope, _cache, _notify, tagged):
    session = _session_returning(_user(is_business=tagged))
    _patch(mock_scope, session)

    request = BuyerRequestService.create_request(
        "USR_1",
        {
            "title": "Cassava",
            "description": "Fresh cassava roots",
            "quantity": 20,
            "unit": "tonne",
        },
    )

    assert isinstance(request, BuyerRequest)
    assert request.is_business is tagged
    assert request.quantity == 20 and request.unit == "tonne"
    assert request.status is RequestStatus.OPEN


@patch.object(BuyerRequestService, "_notify_relevant_sellers")
@patch("app.requests.services.session_scope")
def test_procurement_flag_off_blocks_business_requests(mock_scope, _notify):
    _patch(mock_scope, _session_returning(_user(is_business=True)))
    with patch.object(settings, "BUSINESS_PROCUREMENT_ENABLED", False):
        with pytest.raises(ForbiddenError):
            BuyerRequestService.create_request(
                "USR_1", {"title": "Cassava", "description": "Fresh cassava roots"}
            )
