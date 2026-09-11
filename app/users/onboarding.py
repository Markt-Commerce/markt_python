"""What an account still needs before it can be used.

Registration used to collect name, phone, shop details and an address before
it ever called the API, and only then asked for the email code. Three things
fell out of that, all of them bugs rather than taste:

  * Nothing existed until the last screen. The whole signup lived in a React
    context, so killing the app lost it.
  * A duplicate email surfaced at the end, four screens after the field that
    caused it, as "registration failed".
  * The account was created logged-in but unverified, while login refuses an
    unverified account -- so anyone who closed the app before the last screen
    was locked out of the account they had just made.

The order is now the standard one: create and verify the identity first, then
fill in the profile as authenticated updates. That makes "is this account
finished?" a real question the server has to answer, because the client can
be interrupted at any point and has to know where to resume.

This module is that answer, in one place, so the register response, the
profile response and the mobile router cannot drift apart.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Ordered: the first unmet step is the one to resume at.
VERIFY_EMAIL = "verify_email"
BUYER_PROFILE = "buyer_profile"
SELLER_PROFILE = "seller_profile"


def _buyer_complete(user) -> bool:
    buyer = getattr(user, "buyer_account", None)
    return bool(buyer and (buyer.buyername or "").strip())


def _seller_complete(user) -> bool:
    seller = getattr(user, "seller_account", None)
    return bool(
        seller
        and (seller.shop_name or "").strip()
        and (seller.description or "").strip()
    )


def profile_complete(user) -> bool:
    """True when every role the account holds has the fields it needs.

    Both roles are checked, not just the current one: an account that added a
    shop later is not finished because its buyer half happens to be filled in.
    """
    if user.is_buyer and not _buyer_complete(user):
        return False
    if user.is_seller and not _seller_complete(user):
        return False
    # Neither role means registration did not finish at all.
    return bool(user.is_buyer or user.is_seller)


def next_step(user) -> Optional[str]:
    """The step to resume at, or None when the account is ready to use.

    Email verification comes first deliberately. It is the only step that
    cannot be done later -- an unverified account cannot log back in -- so
    asking for a shop description ahead of it risks stranding the user with a
    filled-in profile they can never reach again.
    """
    if not user.email_verified:
        return VERIFY_EMAIL
    if user.is_buyer and not _buyer_complete(user):
        return BUYER_PROFILE
    if user.is_seller and not _seller_complete(user):
        return SELLER_PROFILE
    return None


def state(user) -> Dict[str, Any]:
    """The whole picture, for the client to route on."""
    return {
        "email_verified": bool(user.email_verified),
        "profile_complete": profile_complete(user),
        "next_step": next_step(user),
    }
