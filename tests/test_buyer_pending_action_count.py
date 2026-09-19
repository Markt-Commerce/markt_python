"""The buyer's Ongoing-tab badge.

The badge deliberately counts substitutions awaiting the buyer's approval, not
ongoing orders. An order in transit needs nothing from the buyer, and a number
that never clears teaches people to ignore badges — including the ones that
matter. Same reasoning as the seller-side count.
"""

from unittest.mock import MagicMock, patch

from app.fulfilment.models import FulfilmentAllocationStatus
from app.orders.services import OrderService


def _count_with(scalar_result):
    """Runs the service against a mocked session, returning (result, filters)."""
    session = MagicMock()
    chain = session.query.return_value.join.return_value.join.return_value
    chain.filter.return_value.scalar.return_value = scalar_result

    scope = MagicMock()
    scope.__enter__ = MagicMock(return_value=session)
    scope.__exit__ = MagicMock(return_value=False)

    with patch("app.orders.services.read_scope", return_value=scope):
        value = OrderService.get_buyer_pending_action_count(7)
    return value, chain.filter.call_args


def test_returns_the_count():
    value, _ = _count_with(3)
    assert value == 3


def test_none_becomes_zero():
    """`.scalar()` returns None when nothing matches; a badge needs a number."""
    value, _ = _count_with(None)
    assert value == 0


def test_filters_on_awaiting_buyer_approval_only():
    """The whole point of the badge.

    Counting any active allocation would make it a count of in-flight orders,
    which is exactly what it must not be.
    """
    _, call = _count_with(1)
    rendered = " ".join(str(a) for a in call[0])

    assert "AWAITING_BUYER_APPROVAL" in rendered.upper() or any(
        arg.right.value is FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL
        for arg in call[0]
        if hasattr(arg, "right") and hasattr(arg.right, "value")
    ), f"expected a filter on AWAITING_BUYER_APPROVAL, got: {rendered}"


def test_scopes_to_the_buyer():
    _, call = _count_with(1)
    rendered = " ".join(str(a) for a in call[0])
    assert "buyer_id" in rendered, f"count must be scoped to the buyer, got: {rendered}"


def test_uses_read_scope_not_session_scope():
    """A badge is polled. session_scope commits on exit, and a commit expires
    every instance it loaded — the same N+1 shape fixed elsewhere in this file.
    """
    import inspect

    source = inspect.getsource(OrderService.get_buyer_pending_action_count)
    assert "read_scope" in source
    assert "session_scope" not in source
