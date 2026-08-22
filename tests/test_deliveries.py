"""Unit tests for the delivery QR proof-of-delivery flow."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.deliveries.models import AssignmentStatus, LogisticalStatus
from app.deliveries.services import DeliveryService
from app.libs.errors import ValidationError
from app.orders.models import OrderItem, OrderStatus


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
@patch("app.wallet.services.WalletService.settle_order_item")
def test_confirm_order_qr_code_settles_every_item_and_completes_order(
    mock_settle, mock_update_status
):
    item_a = SimpleNamespace(id=1, status=OrderItem.Status.PROCESSING, seller_id=7)
    item_b = SimpleNamespace(id=2, status=OrderItem.Status.PROCESSING, seller_id=8)
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
    assert mock_settle.call_count == 2
    assert assignment.logistical_status == LogisticalStatus.COMPLETED
    mock_update_status.assert_called_once_with("ORD_1", OrderStatus.DELIVERED)


@patch("app.orders.services.OrderService.update_order_status")
@patch("app.wallet.services.WalletService.settle_order_item")
def test_confirm_order_qr_code_rejects_wrong_code(mock_settle, mock_update_status):
    assignment = SimpleNamespace(
        escrow_qr_code="QR123", status=AssignmentStatus.ACCEPTED
    )
    session = _session_with(assignment, order=None)

    with patch("app.deliveries.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ValidationError):
            DeliveryService.confirm_order_qr_code("DEL_1", "ORD_1", "WRONG")

    mock_settle.assert_not_called()
    mock_update_status.assert_not_called()
