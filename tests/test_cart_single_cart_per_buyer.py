"""Regression tests for the cart that would not clear after checkout.

Three defects compounded:

1. `Cart.expires_at` defaulted to `datetime.utcnow() + timedelta(days=30)` --
   an expression, so SQLAlchemy stored the *result* as a scalar default
   computed once at import. Every cart a process created got the same
   timestamp, and once that moment passed, new carts were born expired.
2. The read path filtered on `expires_at > now()`, so an expired cart was
   invisible and the next add-to-cart created another alongside it.
3. Every cart lookup used `.first()` with no ordering, and the clear paths had
   no expiry filter while the read path did -- so checkout could clear one
   cart while the app went on reading another.

The symptom: pay for an item, go back to the cart, and it is still there.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from app.cart.models import CART_TTL, Cart, _default_expires_at
from app.cart.services import CartService


# ---------------------------------------------------------------------------
# 1. The default has to be evaluated per row, not once at import
# ---------------------------------------------------------------------------


def test_expires_at_default_is_callable_not_a_frozen_timestamp():
    """The whole bug started here.

    `is_callable` False means SQLAlchemy captured one timestamp at import and
    hands it to every row it ever inserts.
    """
    default = Cart.__table__.c.expires_at.default
    assert default.is_callable, (
        "Cart.expires_at default must be a callable evaluated per row. A bare "
        "expression is computed once at import, so every cart created by a "
        "process shares one expiry and eventually they are all born expired."
    )


def test_expires_at_default_advances_between_calls():
    first = _default_expires_at()
    second = _default_expires_at()
    assert second >= first
    # And it is actually in the future, which the frozen default stopped being.
    assert first > datetime.utcnow()
    assert first <= datetime.utcnow() + CART_TTL + timedelta(seconds=5)


# ---------------------------------------------------------------------------
# 2. One resolver, used by readers and clearers alike
# ---------------------------------------------------------------------------


def _session_returning(cart):
    """A session whose query chain ends in `cart`, recording the calls made."""
    session = MagicMock()
    chain = session.query.return_value.filter_by.return_value
    chain.options.return_value = chain
    chain.order_by.return_value.first.return_value = cart
    return session, chain


def test_resolve_cart_orders_deterministically():
    """`.first()` with no ORDER BY lets Postgres pick. Two callers doing that
    on the same buyer could each get a different cart."""
    cart = Cart()
    session, chain = _session_returning(cart)

    assert CartService.resolve_cart(session, 1) is cart
    chain.order_by.assert_called_once()


def test_resolve_cart_does_not_hide_expired_carts():
    """An expired cart is still the buyer's cart.

    Filtering it out is what caused a second cart to be created next to it,
    which is how a buyer ended up with three.
    """
    session, _ = _session_returning(Cart())

    CartService.resolve_cart(session, 1)

    filters = [str(c) for c in session.query.return_value.filter.call_args_list]
    assert not filters, (
        "resolve_cart must not filter on expires_at -- hiding an expired cart "
        "is what let duplicates accumulate."
    )


def test_resolve_cart_filters_by_buyer():
    session, _ = _session_returning(Cart())

    CartService.resolve_cart(session, 42)

    session.query.return_value.filter_by.assert_called_once_with(buyer_id=42)


# ---------------------------------------------------------------------------
# 3. The database makes the duplicate state unrepresentable
# ---------------------------------------------------------------------------


def test_carts_have_a_unique_constraint_on_buyer_id():
    constraints = {
        c.name
        for c in Cart.__table__.constraints
        if getattr(c, "columns", None)
        and {col.name for col in c.columns} == {"buyer_id"}
    }
    assert "uq_carts_buyer_id" in constraints, (
        "One cart per buyer must be enforced in the database. Without it, the "
        "various .first() lookups can each land on a different row."
    )


# ---------------------------------------------------------------------------
# 4. Cache work must never fail the thing it is optimising
# ---------------------------------------------------------------------------


def test_invalidate_cart_cache_survives_redis_being_down(monkeypatch, caplog):
    """Cache invalidation runs inside payment completion.

    The failure modes are not symmetric: a missed invalidation costs one stale
    read, while raising here costs a *paid* order its completion. This is also
    what CI hits -- the unit-test job has no Redis.
    """
    from redis.exceptions import ConnectionError as RedisConnectionError

    from external import redis as redis_module

    def boom(*_args, **_kwargs):
        raise RedisConnectionError("Error 111 connecting to localhost:6379")

    monkeypatch.setattr(redis_module.redis_client, "delete", boom, raising=False)

    CartService._invalidate_cart_cache(1)  # must not raise


def test_cache_cart_survives_redis_being_down(monkeypatch):
    """Same reasoning for the write side: a Redis outage should not turn
    add-to-cart into a 500."""
    from redis.exceptions import ConnectionError as RedisConnectionError

    from external import redis as redis_module

    def boom(*_args, **_kwargs):
        raise RedisConnectionError("Error 111 connecting to localhost:6379")

    monkeypatch.setattr(redis_module.redis_client, "set", boom, raising=False)

    cart = Cart()
    cart.id = 1
    cart.buyer_id = 1
    cart.coupon_code = None
    cart.expires_at = datetime.utcnow() + CART_TTL
    cart.items = []

    CartService._cache_cart(cart)  # must not raise
