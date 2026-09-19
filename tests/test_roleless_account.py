"""An account that has not picked a role yet.

Signing in through Google or Apple creates exactly this: the provider proves
the address, the app then asks whether you are here to buy or to sell, and
the account has no buyer row and no seller row until that is answered.

Anything interrupting that gap -- a killed app, a failed request, a flat
battery -- used to leave an account that could never be logged into again.
Login raised "No valid account type found", a 401 with nothing the person
holding the phone could do about it, and every way to add a role needs a
session, which is what login was refusing to issue.
"""

from types import SimpleNamespace

import pytest

from app.users.onboarding import (
    CHOOSE_ROLE,
    VERIFY_EMAIL,
    BUYER_PROFILE,
    SELLER_PROFILE,
    next_step,
    profile_complete,
    state,
)


def account(*, verified=True, buyer=None, seller=None):
    return SimpleNamespace(
        email_verified=verified,
        is_buyer=buyer is not None,
        is_seller=seller is not None,
        buyer_account=buyer,
        seller_account=seller,
    )


def buyer(name="Ada"):
    return SimpleNamespace(buyername=name)


def seller(shop="Shop", desc="Desc"):
    return SimpleNamespace(shop_name=shop, description=desc)


class TestTheStateMachineAgreesWithItself:
    def test_a_roleless_account_is_told_to_pick_one(self):
        # This returned None -- "ready to use" -- for an account that has
        # nothing to use the app *as*.
        assert next_step(account()) == CHOOSE_ROLE

    def test_next_step_and_profile_complete_no_longer_disagree(self):
        # profile_complete said False while next_step said None, and the
        # client believed next_step. That is how an OAuth signup walked past
        # role selection into an app it had no role in.
        a = account()
        assert profile_complete(a) is False
        assert next_step(a) is not None

    def test_verification_still_comes_first(self):
        # An unverified roleless account is asked for the code, not the
        # role: the code is the step that cannot be done later.
        assert next_step(account(verified=False)) == VERIFY_EMAIL

    def test_a_buyer_with_no_name_is_sent_to_the_buyer_form(self):
        assert next_step(account(buyer=buyer(""))) == BUYER_PROFILE

    def test_a_seller_with_no_shop_is_sent_to_the_seller_form(self):
        assert next_step(account(seller=seller("", ""))) == SELLER_PROFILE

    def test_a_finished_buyer_has_nothing_left_to_do(self):
        a = account(buyer=buyer())
        assert next_step(a) is None
        assert profile_complete(a) is True

    def test_the_state_block_carries_the_step(self):
        assert state(account())["next_step"] == CHOOSE_ROLE


class TestEveryUnfinishedAccountHasAStep:
    @pytest.mark.parametrize(
        "a",
        [
            account(verified=False),
            account(),
            account(buyer=buyer("")),
            account(seller=seller("", "")),
        ],
    )
    def test_an_incomplete_account_always_says_what_is_missing(self, a):
        # The invariant the client routes on: if it is not finished, there
        # is somewhere to send the person. A screen with no next step and no
        # completion is a dead end.
        assert profile_complete(a) is False
        assert next_step(a) is not None


class TestLoginNoLongerLocksThemOut:
    def test_the_dead_end_error_is_gone(self):
        import inspect

        from app.users.services import AuthService

        source = inspect.getsource(AuthService.login_user)
        assert "No valid account type found" not in source

    def test_a_roleless_login_does_not_try_to_set_a_role(self):
        # current_role's setter rejects None and rejects a role the account
        # does not hold, so setting it unconditionally would swap one 401
        # for a 500.
        import inspect

        from app.users.services import AuthService

        source = inspect.getsource(AuthService.login_user)
        assert "if account_type is not None:" in source
