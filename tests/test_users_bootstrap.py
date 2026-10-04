"""GET /users/bootstrap: the app's start-up payload in one request.

Services are patched throughout; nothing here touches a database or Redis.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.users.bootstrap import build_bootstrap
from app.users.schemas import BootstrapSchema
from main.setup import create_app

PROFILE = {"id": "USR_TEST0001", "email": "ada@example.com", "username": "ada"}
GAM_ME = {"lifetime_points": 120, "badges_count": 2}
UNSEEN = {"badges": [], "tiers": [], "streak": None}


def _user(role="buyer", is_buyer=True, is_seller=False, seller_active=True):
    return SimpleNamespace(
        id="USR_TEST0001",
        current_role=role,
        is_buyer=is_buyer,
        is_seller=is_seller,
        seller_account=(
            SimpleNamespace(id=7, is_active=seller_active) if is_seller else None
        ),
    )


@pytest.fixture
def services():
    with patch(
        "app.users.services.UserService.get_user_profile", return_value=PROFILE
    ) as profile, patch(
        "app.notifications.services.NotificationService.get_user_notifications",
        return_value={"pagination": {"total_items": 3}},
    ) as notifications, patch(
        "app.cart.services.CartService.get_cart_summary",
        return_value={"item_count": 4},
    ) as cart, patch(
        "app.orders.services.SellerOrderService.get_pending_action_count",
        return_value=5,
    ) as pending, patch(
        "app.gamification.services.get_me", return_value=GAM_ME
    ) as gam_me, patch(
        "app.gamification.services.get_unseen_achievements", return_value=UNSEEN
    ) as unseen:
        yield SimpleNamespace(
            profile=profile,
            notifications=notifications,
            cart=cart,
            pending=pending,
            gam_me=gam_me,
            unseen=unseen,
        )


def test_buyer_gets_cart_badge_and_no_seller_badge(services):
    out = build_bootstrap(_user())
    assert out["profile"] == PROFILE
    assert out["unread_notifications"] == 3
    assert out["cart_item_count"] == 4
    assert out["seller_needs_action"] is None
    assert out["gamification"] == GAM_ME
    assert out["unseen_achievements"] == UNSEEN
    # Only unread notifications, the same query the badge endpoint runs.
    assert services.notifications.call_args.kwargs["unread_only"] is True
    services.pending.assert_not_called()


def test_seller_gets_pending_badge_and_no_cart_badge(services):
    out = build_bootstrap(_user(role="seller", is_buyer=True, is_seller=True))
    assert out["seller_needs_action"] == 5
    assert out["cart_item_count"] is None
    services.pending.assert_called_once_with(7)
    services.cart.assert_not_called()


def test_inactive_seller_account_gets_no_badge_rather_than_an_error(services):
    out = build_bootstrap(
        _user(role="seller", is_buyer=False, is_seller=True, seller_active=False)
    )
    assert out["seller_needs_action"] is None
    services.pending.assert_not_called()


def test_one_failing_section_is_null_and_the_rest_still_arrive(services):
    services.gam_me.side_effect = RuntimeError("redis down")
    out = build_bootstrap(_user())
    assert out["gamification"] is None
    assert out["profile"] == PROFILE
    assert out["cart_item_count"] == 4
    assert out["unseen_achievements"] == UNSEEN


def test_profile_failure_fails_the_request(services):
    # The app cannot open without the profile, so it is not swallowed.
    services.profile.side_effect = ValueError("no such user")
    with pytest.raises(ValueError):
        build_bootstrap(_user())


def test_schema_keeps_zero_distinct_from_null():
    # The profile section is UserProfileSchema, covered by the profile tests;
    # it derives onboarding state from a real User, so it is left out here.
    dumped = BootstrapSchema().dump(
        {
            "unread_notifications": 0,
            "cart_item_count": None,
            "seller_needs_action": None,
            "gamification": None,
            "unseen_achievements": None,
        }
    )
    assert dumped["unread_notifications"] == 0
    assert dumped["cart_item_count"] is None
    assert dumped["gamification"] is None


@pytest.fixture
def client():
    flask_app, _socketio = create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


# The profile section derives onboarding state from a real User; a dict
# stands in for it here, so that one helper is stubbed.
@patch(
    "app.users.onboarding.state",
    return_value={"email_verified": True, "profile_complete": True, "next_step": None},
)
@patch("app.users.bootstrap.build_bootstrap")
@patch("flask_login.utils._get_user")
def test_route_returns_the_payload(mock_get_user, mock_build, _state, client):
    user = MagicMock()
    user.is_authenticated = True
    mock_get_user.return_value = user
    mock_build.return_value = {
        "profile": PROFILE,
        "unread_notifications": 1,
        "cart_item_count": 2,
        "seller_needs_action": None,
        "gamification": None,
        "unseen_achievements": None,
    }

    response = client.get("/api/v1/users/bootstrap")

    assert response.status_code == 200
    body = response.get_json()
    assert body["unread_notifications"] == 1
    assert body["cart_item_count"] == 2
    assert body["profile"]["username"] == "ada"
    mock_build.assert_called_once_with(user)


@patch("flask_login.utils._get_user")
def test_route_requires_sign_in(mock_get_user, client):
    anon = MagicMock()
    anon.is_authenticated = False
    mock_get_user.return_value = anon

    assert client.get("/api/v1/users/bootstrap").status_code == 401
