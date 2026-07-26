"""Signal handlers that translate domain events into point awards and badge
evaluations (spec §5.3).

Every handler is wrapped so a gamification failure can never break the host
action that emitted the signal — awarding points is strictly a side-effect.
Importing this module connects the handlers; it is imported from routes.py so
registration happens when the blueprint loads.
"""

import functools
import logging
from datetime import datetime

from app.signals import (
    order_completed,
    order_reversed,
    post_created,
    post_reaction_added,
    review_created,
    profile_completed,
    referral_first_paid,
    daily_login,
    seller_verified,
)
from . import services
from .constants import REF_ORDER, REF_POST, REF_REVIEW, REF_USER, REF_REACTION

logger = logging.getLogger(__name__)


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(sender, **kw):
        try:
            return fn(sender, **kw)
        except Exception as e:  # pragma: no cover - never break the emitter
            logger.error(f"gamification handler {fn.__name__} failed: {e}")

    return wrapper


def _order_id_of(order=None, order_id=None):
    """Accept either an ORM order (possibly detached) or an explicit id."""
    if order_id:
        return order_id
    return getattr(order, "id", None)


def _resolve_participants(order_id):
    """(buyer_user_id, {seller_user_ids}) for an order, freshly attached.

    Signals are emitted post-commit so any passed ORM instance is detached; we
    re-query in our own session to safely walk buyer/items/sellers.
    """
    from app.libs.session import session_scope
    from app.orders.models import Order, OrderItem
    from external.database import db

    buyer_user_id = None
    seller_ids = set()
    with session_scope() as session:
        order = (
            session.query(Order)
            .options(
                db.joinedload(Order.buyer),
                db.joinedload(Order.items).joinedload(OrderItem.seller),
            )
            .get(order_id)
        )
        if order is None:
            return (None, set())
        if order.buyer:
            buyer_user_id = order.buyer.user_id
        for item in order.items or []:
            if item.seller and item.seller.user_id:
                seller_ids.add(item.seller.user_id)
    return (buyer_user_id, seller_ids)


@order_completed.connect
@_safe
def _on_order_completed(sender, order=None, order_id=None, **kw):
    oid = _order_id_of(order, order_id)
    if not oid:
        return
    buyer_user_id, seller_ids = _resolve_participants(oid)
    if buyer_user_id:
        services.award_by_reason(
            buyer_user_id, "order_completed_buyer", ref_type=REF_ORDER, ref_id=oid
        )
        services.evaluate_badges_for(buyer_user_id, "order.completed")

    for seller_user_id in seller_ids:
        services.award_by_reason(
            seller_user_id,
            "order_completed_seller",
            ref_type=REF_ORDER,
            ref_id=oid,
        )
        services.record_sale(seller_user_id)
        services.evaluate_badges_for(seller_user_id, "order.completed")


@order_reversed.connect
@_safe
def _on_order_reversed(sender, order=None, order_id=None, **kw):
    oid = _order_id_of(order, order_id)
    if not oid:
        return
    buyer_user_id, seller_ids = _resolve_participants(oid)
    if buyer_user_id:
        services.reverse_award(
            buyer_user_id,
            "order_completed_buyer",
            REF_ORDER,
            oid,
            "order_reversed",
        )
    for seller_user_id in seller_ids:
        services.reverse_award(
            seller_user_id,
            "order_completed_seller",
            REF_ORDER,
            oid,
            "order_reversed",
        )


@post_created.connect
@_safe
def _on_post_created(sender, post=None, **kw):
    if post is None or not getattr(post, "user_id", None):
        return
    services.award_by_reason(
        post.user_id, "post_created", ref_type=REF_POST, ref_id=post.id
    )
    services.evaluate_badges_for(post.user_id, "post.created")


@post_reaction_added.connect
@_safe
def _on_post_reaction_added(sender, post=None, reactor_id=None, **kw):
    if post is None or not getattr(post, "user_id", None):
        return
    # Don't reward self-reactions.
    if reactor_id and reactor_id == post.user_id:
        return
    # ref uniquely identifies (post, reactor) so the same reactor can't farm the
    # same post; the daily cap bounds the rest.
    ref = f"{post.id}:{reactor_id}"
    services.award_by_reason(
        post.user_id, "post_reaction_received", ref_type=REF_REACTION, ref_id=ref
    )
    services.evaluate_badges_for(post.user_id, "post.reaction_added")


@review_created.connect
@_safe
def _on_review_created(sender, review=None, **kw):
    if review is None:
        return
    reviewer_id = getattr(review, "user_id", None)
    review_id = getattr(review, "id", None)
    rating = getattr(review, "rating", None)
    product_id = getattr(review, "product_id", None)
    # Reviews carry no media in the current schema, so all reviews are text-only.
    # getattr keeps this forward-compatible if a photo field is added later.
    has_photo = bool(
        getattr(review, "images", None) or getattr(review, "has_photo", False)
    )

    if reviewer_id and review_id is not None:
        reason = "review_with_photo" if has_photo else "review_text_only"
        services.award_by_reason(
            reviewer_id, reason, ref_type=REF_REVIEW, ref_id=review_id
        )

    # Resolve the reviewed seller in a fresh session (signal fires post-commit,
    # so `review.product.seller` would otherwise be a detached lazy-load).
    if product_id and rating is not None:
        seller_user_id = _seller_user_of_product(product_id)
        if seller_user_id:
            services.record_review(seller_user_id, rating)
            services.evaluate_badges_for(seller_user_id, "review.created")


def _seller_user_of_product(product_id):
    from app.libs.session import session_scope
    from app.products.models import Product

    try:
        with session_scope() as session:
            product = session.query(Product).get(product_id)
            seller = getattr(product, "seller", None) if product else None
            return getattr(seller, "user_id", None) if seller else None
    except Exception:
        return None


@profile_completed.connect
@_safe
def _on_profile_completed(sender, user_id=None, **kw):
    if not user_id:
        return
    services.award_by_reason(
        user_id, "profile_completed", ref_type=REF_USER, ref_id=user_id
    )
    services.evaluate_badges_for(user_id, "profile.completed")


@referral_first_paid.connect
@_safe
def _on_referral_first_paid(sender, referrer_id=None, referee_id=None, **kw):
    if not referrer_id:
        return
    services.award_by_reason(
        referrer_id, "referral_first_paid", ref_type=REF_USER, ref_id=referee_id
    )


@daily_login.connect
@_safe
def _on_daily_login(sender, user_id=None, **kw):
    if not user_id:
        return
    day = datetime.utcnow().strftime("%Y%m%d")
    services.award_by_reason(
        user_id, "daily_first_login", ref_type="day", ref_id=f"{user_id}:{day}"
    )


@seller_verified.connect
@_safe
def _on_seller_verified(sender, user_id=None, **kw):
    if not user_id:
        return
    services.evaluate_badges_for(user_id, "seller.verified")
