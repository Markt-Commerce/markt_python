"""Where an interrupted signup resumes.

Registration used to build the whole account in memory and POST it on the
last screen. Now the account exists from the first screen, which means the
client can be killed at any point -- so the server has to be able to say what
is still missing. These tests pin that answer down.

No database: the logic is pure inspection of an account's fields, and the
value of testing it is in the edge cases (a two-role account, an unverified
one, a half-filled shop), not in the persistence.
"""

from types import SimpleNamespace

from app.users.onboarding import (
    BUYER_PROFILE,
    SELLER_PROFILE,
    VERIFY_EMAIL,
    next_step,
    profile_complete,
    state,
)


def _user(**over):
    base = dict(
        email_verified=True,
        is_buyer=False,
        is_seller=False,
        buyer_account=None,
        seller_account=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _buyer(name="Ada Obi"):
    return SimpleNamespace(buyername=name)


def _seller(shop_name="Ada Fabrics", description="Ankara and lace."):
    return SimpleNamespace(shop_name=shop_name, description=description)


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_verification_comes_before_the_profile():
    """The one step that cannot be deferred goes first.

    An unverified account cannot log back in, so sending someone to fill in a
    shop description first risks stranding them with a finished profile on an
    account they can never reach again.
    """
    user = _user(email_verified=False, is_buyer=True, buyer_account=_buyer(None))
    assert next_step(user) == VERIFY_EMAIL


def test_a_verified_buyer_without_a_name_resumes_at_the_buyer_profile():
    user = _user(is_buyer=True, buyer_account=_buyer(None))
    assert next_step(user) == BUYER_PROFILE


def test_a_verified_seller_without_a_shop_resumes_at_the_shop():
    user = _user(is_seller=True, seller_account=_seller(None, None))
    assert next_step(user) == SELLER_PROFILE


def test_a_finished_account_has_no_next_step():
    user = _user(is_buyer=True, buyer_account=_buyer())
    assert next_step(user) is None
    assert profile_complete(user) is True


# ---------------------------------------------------------------------------
# The cases that are easy to get wrong
# ---------------------------------------------------------------------------


def test_a_half_filled_shop_is_not_complete():
    """A shop name with no description is not a shop anyone can judge."""
    user = _user(is_seller=True, seller_account=_seller(description=None))
    assert profile_complete(user) is False
    assert next_step(user) == SELLER_PROFILE


def test_whitespace_is_not_a_name():
    user = _user(is_buyer=True, buyer_account=_buyer("   "))
    assert profile_complete(user) is False


def test_both_roles_must_both_be_complete():
    """An account that added a shop later is not finished just because its
    buyer half was filled in during signup."""
    user = _user(
        is_buyer=True,
        is_seller=True,
        buyer_account=_buyer(),
        seller_account=_seller(None, None),
    )
    assert profile_complete(user) is False
    assert next_step(user) == SELLER_PROFILE


def test_a_missing_profile_row_is_incomplete_not_a_crash():
    """`is_buyer` with no Buyer row should never have happened, but reading it
    must report an unfinished account rather than raise on a browse."""
    user = _user(is_buyer=True, buyer_account=None)
    assert profile_complete(user) is False
    assert next_step(user) == BUYER_PROFILE


def test_an_account_with_no_role_at_all_is_incomplete():
    assert profile_complete(_user()) is False


# ---------------------------------------------------------------------------
# The payload the client routes on
# ---------------------------------------------------------------------------


def test_state_reports_all_three_fields():
    user = _user(email_verified=False, is_buyer=True, buyer_account=_buyer())
    assert state(user) == {
        "email_verified": False,
        "profile_complete": True,
        "next_step": VERIFY_EMAIL,
    }
