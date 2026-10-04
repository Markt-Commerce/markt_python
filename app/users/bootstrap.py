"""Everything the app needs on open, in one response.

A signed-in cold start used to make five separate requests for this: the
profile, the unread-notification badge, the cart (or seller pending) badge,
the gamification summary and any unseen achievements. Over HTTP/1.1 each is
its own connection and round trip, and they competed with the feed for the
same few connections. This assembles them server-side, where each is a query
or two away.

Additive: every one of those endpoints still exists and is still what the app
uses after start-up, when a single badge changes.

Each section is built independently. A failure in one (Redis down for the
gamification rank, say) returns null for that section and is logged; it never
fails the whole response, because the profile alone is what the app cannot
open without. The client treats a null section as "fetch it the old way".
"""

import logging

logger = logging.getLogger(__name__)


def _section(name, build):
    try:
        return build()
    except Exception as e:  # one broken badge must not cost the user the app
        logger.warning(f"bootstrap: {name} unavailable: {e}", exc_info=True)
        return None


def _unread_notifications(user_id):
    from app.notifications.services import NotificationService

    # Same query the /notifications/unread/count route runs.
    notifications = NotificationService.get_user_notifications(
        user_id, page=1, per_page=1, unread_only=True
    )
    return notifications["pagination"]["total_items"]


def _cart_item_count(user):
    from app.cart.services import CartService

    return CartService.get_cart_summary(user.id).get("item_count", 0)


def _seller_needs_action(user):
    from app.orders.services import SellerOrderService

    return SellerOrderService.get_pending_action_count(user.seller_account.id)


def build_bootstrap(user):
    """Assemble the start-up payload for `user` (the authenticated User)."""
    from app.gamification import services as gamification
    from .services import UserService

    # The profile is the one section that is not optional: the app cannot
    # pick a role or a tab bar without it, so its errors propagate to the
    # route exactly as they do from GET /users/profile.
    profile = UserService.get_user_profile(user.id)

    # The badge the app shows depends on the mode it is in, mirroring the
    # client's CartProvider: buyers see their cart, sellers the orders that
    # need them. The same checks as @buyer_required / @seller_required guard
    # each, so a mode the account cannot use yields null rather than a 403.
    role = user.current_role
    cart_item_count = None
    seller_needs_action = None
    if role == "buyer" and user.is_buyer:
        cart_item_count = _section("cart", lambda: _cart_item_count(user))
    elif (
        role == "seller"
        and user.is_seller
        and user.seller_account
        and user.seller_account.is_active
    ):
        seller_needs_action = _section(
            "seller_pending", lambda: _seller_needs_action(user)
        )

    return {
        "profile": profile,
        "unread_notifications": _section(
            "notifications", lambda: _unread_notifications(user.id)
        ),
        "cart_item_count": cart_item_count,
        "seller_needs_action": seller_needs_action,
        "gamification": _section("gamification", lambda: gamification.get_me(user.id)),
        "unseen_achievements": _section(
            "unseen_achievements",
            lambda: gamification.get_unseen_achievements(user.id),
        ),
    }
