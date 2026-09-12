"""Unit tests for the buyer-facing POD code endpoint (10.6) --
DeliveryService.get_buyer_pod_code."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.deliveries.models import AssignmentStatus, DeliveryRunOrderPodStatus
from app.deliveries.services import DeliveryService
from app.libs.errors import ForbiddenError


def _order(**overrides):
    defaults = dict(buyer=SimpleNamespace(user_id="USR_BUYER1"))
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _query_side_effect(order_mock, assignment_mock, run_order_mock):
    def side_effect(model):
        name = getattr(model, "__name__", None)
        if name == "Order":
            return order_mock
        if name == "DeliveryOrderAssignment":
            return assignment_mock
        if name == "DeliveryRunOrder":
            return run_order_mock
        return MagicMock()

    return side_effect


@patch("app.deliveries.services.session_scope")
def test_get_buyer_pod_code_forbidden_for_non_owner(mock_scope):
    order_mock = MagicMock()
    order_mock.options.return_value.get.return_value = _order()

    session = MagicMock()
    session.query.side_effect = _query_side_effect(order_mock, MagicMock(), MagicMock())
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ForbiddenError):
        DeliveryService.get_buyer_pod_code("ORD_1", "SOMEONE_ELSE")


@patch("app.deliveries.services.session_scope")
def test_get_buyer_pod_code_returns_single_order_code_when_accepted(mock_scope):
    order_mock = MagicMock()
    order_mock.options.return_value.get.return_value = _order()

    assignment_mock = MagicMock()
    assignment_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        SimpleNamespace(status=AssignmentStatus.ACCEPTED, escrow_qr_code="CODE123")
    )

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        order_mock, assignment_mock, MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    result = DeliveryService.get_buyer_pod_code("ORD_1", "USR_BUYER1")

    assert result == {"ready": True, "system": "single_order", "code": "CODE123"}


@patch("app.deliveries.services.session_scope")
def test_get_buyer_pod_code_falls_back_to_run_when_no_single_order_assignment(
    mock_scope,
):
    order_mock = MagicMock()
    order_mock.options.return_value.get.return_value = _order()

    assignment_mock = MagicMock()
    assignment_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        None
    )

    run_order_mock = MagicMock()
    run_order_mock.filter_by.return_value.first.return_value = SimpleNamespace(
        pod_status=DeliveryRunOrderPodStatus.QR_ISSUED, qr_code="RUNCODE9"
    )

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        order_mock, assignment_mock, run_order_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    result = DeliveryService.get_buyer_pod_code("ORD_1", "USR_BUYER1")

    assert result == {"ready": True, "system": "run", "code": "RUNCODE9"}


@patch("app.deliveries.services.session_scope")
def test_get_buyer_pod_code_not_ready_when_neither_system_has_a_code(mock_scope):
    order_mock = MagicMock()
    order_mock.options.return_value.get.return_value = _order()

    assignment_mock = MagicMock()
    assignment_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        None
    )

    run_order_mock = MagicMock()
    run_order_mock.filter_by.return_value.first.return_value = SimpleNamespace(
        pod_status=DeliveryRunOrderPodStatus.PENDING, qr_code=None
    )

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        order_mock, assignment_mock, run_order_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    result = DeliveryService.get_buyer_pod_code("ORD_1", "USR_BUYER1")

    assert result == {"ready": False, "system": None, "code": None}
