"""Unit tests for the delivery QR proof-of-delivery flow and pickup wiring."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.deliveries.models import AssignmentStatus, LogisticalStatus
from app.deliveries.services import DeliveryService
from app.libs.errors import ValidationError
from app.orders.models import OrderItem, OrderStatus


def _make_item(id, status, seller_id):
    """A SimpleNamespace that behaves like a real OrderItem for transition_to."""
    item = SimpleNamespace(id=id, status=status, seller_id=seller_id, delivered_at=None)
    item.transition_to = lambda new_status, _item=item: OrderItem.transition_to(
        _item, new_status
    )
    return item


def _session_with(assignment, order):
    session = MagicMock()

    def query_side_effect(model):
        mock = MagicMock()
        if model.__name__ == "DeliveryOrderAssignment":
            mock.filter_by.return_value.first.return_value = assignment
        elif model.__name__ == "Order":
            mock.filter_by.return_value.first.return_value = order
        else:
            mock.filter_by.return_value.first.return_value = None
        return mock

    session.query.side_effect = query_side_effect
    return session


@patch("app.orders.services.OrderService.update_order_status")
def test_confirm_order_qr_code_starts_settlement_hold_and_completes_order(
    mock_update_status,
):
    item_a = _make_item(1, OrderItem.Status.PROCESSING, seller_id=7)
    item_b = _make_item(2, OrderItem.Status.SHIPPED, seller_id=8)
    order = SimpleNamespace(id="ORD_1", items=[item_a, item_b])
    assignment = SimpleNamespace(
        escrow_qr_code="QR123",
        status=AssignmentStatus.ACCEPTED,
        logistical_status=LogisticalStatus.DELIVERED_PENDING_QR,
    )

    session = _session_with(assignment, order)

    with patch("app.deliveries.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryService.confirm_order_qr_code("DEL_1", "ORD_1", "QR123")

    assert result == {"status": "success", "message": "Order marked as delivered"}
    assert item_a.status == OrderItem.Status.DELIVERED
    assert item_b.status == OrderItem.Status.DELIVERED
    # POD starts the settlement hold, it doesn't pay out immediately -- see
    # WalletService.settle_eligible_order_items (Phase 0: 12h hold).
    assert item_a.delivered_at is not None
    assert item_b.delivered_at is not None
    assert assignment.logistical_status == LogisticalStatus.COMPLETED
    mock_update_status.assert_called_once_with("ORD_1", OrderStatus.DELIVERED)


@patch("app.orders.services.OrderService.update_order_status")
def test_confirm_order_qr_code_skips_cancelled_items(mock_update_status):
    item_a = _make_item(1, OrderItem.Status.SHIPPED, seller_id=7)
    item_b = _make_item(2, OrderItem.Status.CANCELLED, seller_id=8)
    order = SimpleNamespace(id="ORD_1", items=[item_a, item_b])
    assignment = SimpleNamespace(
        escrow_qr_code="QR123",
        status=AssignmentStatus.ACCEPTED,
        logistical_status=LogisticalStatus.DELIVERED_PENDING_QR,
    )

    session = _session_with(assignment, order)

    with patch("app.deliveries.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        DeliveryService.confirm_order_qr_code("DEL_1", "ORD_1", "QR123")

    assert item_a.status == OrderItem.Status.DELIVERED
    assert item_a.delivered_at is not None
    assert item_b.status == OrderItem.Status.CANCELLED
    assert item_b.delivered_at is None


@patch("app.orders.services.OrderService.update_order_status")
def test_confirm_order_qr_code_rejects_when_not_pending_qr(mock_update_status):
    item_a = _make_item(1, OrderItem.Status.SHIPPED, seller_id=7)
    order = SimpleNamespace(id="ORD_1", items=[item_a])
    assignment = SimpleNamespace(
        escrow_qr_code="QR123",
        status=AssignmentStatus.ACCEPTED,
        logistical_status=LogisticalStatus.EN_ROUTE_TO_DROPOFF,
    )

    session = _session_with(assignment, order)

    with patch("app.deliveries.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ValidationError):
            DeliveryService.confirm_order_qr_code("DEL_1", "ORD_1", "QR123")

    assert item_a.status == OrderItem.Status.SHIPPED
    assert item_a.delivered_at is None
    mock_update_status.assert_not_called()


@patch("app.orders.services.OrderService.update_order_status")
def test_confirm_order_qr_code_rejects_wrong_code(mock_update_status):
    assignment = SimpleNamespace(
        escrow_qr_code="QR123", status=AssignmentStatus.ACCEPTED
    )
    session = _session_with(assignment, order=None)

    with patch("app.deliveries.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ValidationError):
            DeliveryService.confirm_order_qr_code("DEL_1", "ORD_1", "WRONG")

    mock_update_status.assert_not_called()


def test_update_assignment_status_pickup_ships_processing_items():
    item_a = _make_item(1, OrderItem.Status.PROCESSING, seller_id=7)
    item_b = _make_item(2, OrderItem.Status.CANCELLED, seller_id=8)
    order = SimpleNamespace(id="ORD_1", items=[item_a, item_b])
    assignment = SimpleNamespace(
        assignment_id="ASG_1",
        order_id="ORD_1",
        logistical_status=LogisticalStatus.ARRIVED_PICKUP,
    )

    session = _session_with(assignment, order)

    with patch("app.deliveries.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryService.update_assignment_status("DEL_1", "ASG_1", "picked_up")

    assert result == {"status": "PICKED_UP"}
    assert item_a.status == OrderItem.Status.SHIPPED
    assert item_b.status == OrderItem.Status.CANCELLED


def test_update_assignment_status_leaves_items_alone_for_other_transitions():
    item_a = _make_item(1, OrderItem.Status.PROCESSING, seller_id=7)
    order = SimpleNamespace(id="ORD_1", items=[item_a])
    assignment = SimpleNamespace(
        assignment_id="ASG_1",
        order_id="ORD_1",
        logistical_status=LogisticalStatus.PICKED_UP,
    )

    session = _session_with(assignment, order)

    with patch("app.deliveries.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryService.update_assignment_status(
            "DEL_1", "ASG_1", "en_route_to_dropoff"
        )

    assert result == {"status": "EN_ROUTE_TO_DROPOFF"}
    assert item_a.status == OrderItem.Status.PROCESSING
