"""Unit tests for DeliveryFailureService: typed delivery-failure
reporting and recovery resolution (10.7, Phase 10)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.deliveries.failure import DeliveryFailureService
from app.deliveries.models import (
    AssignmentStatus,
    DeliveryCostBearer,
    DeliveryFailureOutcome,
    DeliveryFailureReason,
    DeliveryRecoveryAction,
)
from app.libs.errors import ConflictError, NotFoundError, ValidationError
from app.notifications.models import NotificationType
from app.orders.events import OrderEventType
from app.orders.models import OrderItem


def _query_side_effect(**by_name):
    def side_effect(model):
        m = MagicMock()
        name = getattr(model, "__name__", None)
        config = by_name.get(name)
        if config:
            config(m)
        return m

    return side_effect


def _make_item(id, status, product_id):
    return SimpleNamespace(id=id, status=status, product_id=product_id)


# --- report_failure -----------------------------------------------------


@patch("app.deliveries.failure.NotificationService.create_notification")
def test_report_failure_records_reason_and_perishable_flag(mock_notify):
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    item = _make_item(1, OrderItem.Status.SHIPPED, product_id="P1")
    order = SimpleNamespace(items=[item], buyer=SimpleNamespace(user_id="USR_BUYER1"))
    run_order = SimpleNamespace(order_id="ORD_1", order=order)
    handling = SimpleNamespace(product_id="P1")

    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def run_order_query(m):
        m.filter_by.return_value.first.return_value = run_order

    def handling_query(m):
        m.filter.return_value.first.return_value = handling

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query,
        DeliveryRunOrder=run_order_query,
        ProductHandling=handling_query,
    )
    session.add.side_effect = lambda obj: setattr(obj, "id", "DFL_1")

    with patch("app.deliveries.failure.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryFailureService.report_failure(
            "DEL_1",
            "RUN_1",
            "ORD_1",
            DeliveryFailureReason.BUYER_UNAVAILABLE,
            notes="No answer at door",
        )

    assert result["order_id"] == "ORD_1"
    assert result["reason"] == "buyer_unavailable"
    assert result["is_perishable"] is True
    assert result["outcome"] == DeliveryFailureOutcome.PENDING.value
    # Phase 12 (15): buyer notified of the delivery failure.
    mock_notify.assert_called_once()
    assert mock_notify.call_args.kwargs["user_id"] == "USR_BUYER1"
    assert (
        mock_notify.call_args.kwargs["notification_type"]
        == NotificationType.DELIVERY_FAILED
    )
    # 14.2 gap-fill: event log now covers run-based delivery failures too.
    emitted_event = session.add.call_args_list[-1][0][0]
    assert emitted_event.event_type == OrderEventType.ITEM_DELIVERY_FAILED
    assert emitted_event.order_id == "ORD_1"


@patch("app.deliveries.failure.NotificationService.create_notification")
def test_report_failure_not_perishable_when_no_handling_match(mock_notify):
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    item = _make_item(1, OrderItem.Status.SHIPPED, product_id="P1")
    order = SimpleNamespace(items=[item], buyer=SimpleNamespace(user_id="USR_BUYER1"))
    run_order = SimpleNamespace(order_id="ORD_1", order=order)

    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def run_order_query(m):
        m.filter_by.return_value.first.return_value = run_order

    def handling_query(m):
        m.filter.return_value.first.return_value = None

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query,
        DeliveryRunOrder=run_order_query,
        ProductHandling=handling_query,
    )
    session.add.side_effect = lambda obj: setattr(obj, "id", "DFL_1")

    with patch("app.deliveries.failure.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryFailureService.report_failure(
            "DEL_1", "RUN_1", "ORD_1", DeliveryFailureReason.BAD_ADDRESS
        )

    assert result["is_perishable"] is False
    assert result["reason"] == "bad_address"


def test_report_failure_raises_not_found_without_accepted_assignment():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    with patch("app.deliveries.failure.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(NotFoundError):
            DeliveryFailureService.report_failure(
                "DEL_1", "RUN_1", "ORD_1", DeliveryFailureReason.BUYER_REFUSED
            )


def test_report_failure_raises_not_found_when_order_not_in_run():
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def run_order_query(m):
        m.filter_by.return_value.first.return_value = None

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query, DeliveryRunOrder=run_order_query
    )

    with patch("app.deliveries.failure.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(NotFoundError):
            DeliveryFailureService.report_failure(
                "DEL_1", "RUN_1", "ORD_1", DeliveryFailureReason.BUYER_REFUSED
            )


# --- resolve_failure -----------------------------------------------------


def test_resolve_failure_records_action_and_cost_bearer():
    failure = SimpleNamespace(
        id="DFL_1",
        outcome=DeliveryFailureOutcome.PENDING,
        recovery_action=None,
        cost_bearer=None,
        resolution_notes=None,
        resolved_at=None,
        completed_at=None,
        delivery_run_id="RUN_1",
        order_id="ORD_1",
        reason=DeliveryFailureReason.BAD_ADDRESS,
        is_perishable=False,
        reported_at=None,
    )
    session = MagicMock()
    session.query.return_value.get.return_value = failure

    with patch("app.deliveries.failure.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryFailureService.resolve_failure(
            "DFL_1",
            DeliveryRecoveryAction.RETURN_TO_SELLER,
            DeliveryCostBearer.SELLER,
            notes="Address doesn't exist",
        )

    assert result["recovery_action"] == "return_to_seller"
    assert result["cost_bearer"] == "seller"
    assert result["outcome"] == DeliveryFailureOutcome.RESOLVED.value
    assert failure.resolved_at is not None


def test_resolve_failure_raises_not_found_for_missing_failure():
    session = MagicMock()
    session.query.return_value.get.return_value = None

    with patch("app.deliveries.failure.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(NotFoundError):
            DeliveryFailureService.resolve_failure(
                "DFL_1",
                DeliveryRecoveryAction.DISPOSE,
                DeliveryCostBearer.MARKT,
            )


def test_resolve_failure_raises_conflict_when_already_resolved():
    failure = SimpleNamespace(id="DFL_1", outcome=DeliveryFailureOutcome.RESOLVED)
    session = MagicMock()
    session.query.return_value.get.return_value = failure

    with patch("app.deliveries.failure.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ConflictError):
            DeliveryFailureService.resolve_failure(
                "DFL_1",
                DeliveryRecoveryAction.DISPOSE,
                DeliveryCostBearer.MARKT,
            )


# --- complete_recovery -----------------------------------------------------


def test_complete_recovery_marks_completed():
    failure = SimpleNamespace(
        id="DFL_1",
        outcome=DeliveryFailureOutcome.RESOLVED,
        recovery_action=DeliveryRecoveryAction.DISPOSE,
        cost_bearer=DeliveryCostBearer.MARKT,
        resolution_notes="Perishable, disposed same day",
        resolved_at=None,
        completed_at=None,
        delivery_run_id="RUN_1",
        order_id="ORD_1",
        reason=DeliveryFailureReason.BUYER_UNAVAILABLE,
        is_perishable=True,
        reported_at=None,
    )
    session = MagicMock()
    session.query.return_value.get.return_value = failure

    with patch("app.deliveries.failure.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryFailureService.complete_recovery(
            "DFL_1", notes="Confirmed disposed"
        )

    assert result["outcome"] == DeliveryFailureOutcome.COMPLETED.value
    assert failure.completed_at is not None
    assert "Confirmed disposed" in failure.resolution_notes


def test_complete_recovery_raises_validation_when_not_yet_resolved():
    failure = SimpleNamespace(id="DFL_1", outcome=DeliveryFailureOutcome.PENDING)
    session = MagicMock()
    session.query.return_value.get.return_value = failure

    with patch("app.deliveries.failure.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ValidationError):
            DeliveryFailureService.complete_recovery("DFL_1")


def test_complete_recovery_raises_not_found_for_missing_failure():
    session = MagicMock()
    session.query.return_value.get.return_value = None

    with patch("app.deliveries.failure.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(NotFoundError):
            DeliveryFailureService.complete_recovery("DFL_1")
