"""Unit tests for the 14.2 event/audit log: OrderEventService.emit's
transactional-outbox semantics (caller's own session, idempotency dedup)
and OrderService.get_order_events' buyer-ownership check."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import ForbiddenError, NotFoundError
from app.orders.events import ActorType, OrderEvent, OrderEventService, OrderEventType
from app.orders.services import OrderService


def test_emit_uses_the_passed_session_directly():
    """The whole point of the transactional outbox: emit() must never open
    its own session_scope() -- it writes through whatever session the
    caller is already inside."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    event = OrderEventService.emit(
        session,
        order_id="ORD_1",
        event_type=OrderEventType.ORDER_CREATED,
        actor_type=ActorType.BUYER,
        actor_id="1",
    )

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, OrderEvent)
    assert added.order_id == "ORD_1"
    assert added.event_type == OrderEventType.ORDER_CREATED
    assert added.actor_type == ActorType.BUYER
    assert event is added


def test_emit_defaults_actor_type_to_system():
    session = MagicMock()

    OrderEventService.emit(
        session, order_id="ORD_1", event_type=OrderEventType.ITEM_UNFULFILLED
    )

    added = session.add.call_args[0][0]
    assert added.actor_type == ActorType.SYSTEM


def test_emit_is_idempotent_when_key_already_exists():
    session = MagicMock()
    existing = SimpleNamespace(id=99)
    session.query.return_value.filter_by.return_value.first.return_value = existing

    result = OrderEventService.emit(
        session,
        order_id="ORD_1",
        event_type=OrderEventType.ITEM_TIMED_OUT,
        idempotency_key="event:item_timed_out:5",
    )

    assert result is existing
    session.add.assert_not_called()


def test_emit_without_idempotency_key_never_checks_for_duplicates():
    session = MagicMock()

    OrderEventService.emit(
        session, order_id="ORD_1", event_type=OrderEventType.ITEM_ACCEPTED
    )

    session.query.assert_not_called()
    session.add.assert_called_once()


@patch("app.orders.services.session_scope")
def test_get_order_events_returns_chronological_list(mock_scope):
    order = SimpleNamespace(id="ORD_1", buyer_id=42)
    events = [SimpleNamespace(id=1), SimpleNamespace(id=2)]

    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = order
    session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = (
        events
    )
    mock_scope.return_value.__enter__.return_value = session

    result = OrderService.get_order_events("ORD_1", buyer_id=42)

    assert result == events


@patch("app.orders.services.session_scope")
def test_get_order_events_raises_not_found_for_missing_order(mock_scope):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(NotFoundError):
        OrderService.get_order_events("ORD_MISSING", buyer_id=42)


@patch("app.orders.services.session_scope")
def test_get_order_events_raises_forbidden_for_wrong_buyer(mock_scope):
    order = SimpleNamespace(id="ORD_1", buyer_id=42)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = order
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ForbiddenError):
        OrderService.get_order_events("ORD_1", buyer_id=999)
