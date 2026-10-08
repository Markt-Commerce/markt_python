"""A rider on a single order could not say a delivery had failed.

The run flow has had typed failure reporting since 10.7. The
single-order flow had nothing: a rider standing at a door with nobody
behind it could mark the delivery complete, which is a lie, or walk
away and leave the assignment open forever. Neither told the buyer
anything, and neither freed the rider.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.deliveries.failure import DeliveryFailureService
from app.deliveries.models import (
    AssignmentStatus,
    DeliveryFailureOutcome,
    DeliveryFailureReason,
    LogisticalStatus,
)
from app.libs.errors import ConflictError, NotFoundError
from app.orders.models import OrderItem


def _order(buyer_user_id="USR_1"):
    return SimpleNamespace(
        id="ORD_1",
        items=[SimpleNamespace(product_id="PRD_1", status=OrderItem.Status.PROCESSING)],
        buyer=SimpleNamespace(user=SimpleNamespace(id=buyer_user_id)),
    )


def _drive(assignment, order=None, notify=None):
    """Run report_single_order_failure against a stubbed session."""
    session = MagicMock()
    added = []
    session.add.side_effect = added.append

    def query(model):
        q = MagicMock()
        name = getattr(model, "__name__", str(model))
        if name == "DeliveryOrderAssignment":
            q.filter_by.return_value.first.return_value = assignment
        elif name == "Order":
            q.filter_by.return_value.first.return_value = order
        else:  # ProductHandling -- nothing perishable
            q.filter.return_value.first.return_value = None
        return q

    session.query.side_effect = query

    scope = MagicMock()
    scope.return_value.__enter__.return_value = session

    with patch("app.deliveries.failure.session_scope", scope), patch(
        "app.deliveries.failure.OrderEventService.emit"
    ), patch("app.delivery_pricing.order_delivery.advance_buyer_delivery"), patch(
        "app.deliveries.failure.NotificationService.create_notification",
        side_effect=notify or (lambda *a, **k: None),
    ):
        result = DeliveryFailureService.report_single_order_failure(
            "DEL_1", "ASG_1", DeliveryFailureReason.BUYER_UNAVAILABLE, notes="No answer"
        )
    return result, added, session


def _assignment(**overrides):
    data = {
        "assignment_id": "ASG_1",
        "order_id": "ORD_1",
        "status": AssignmentStatus.ACCEPTED,
        "logistical_status": LogisticalStatus.DELIVERED_PENDING_QR,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class TestTheFailureIsRecorded:
    def test_it_writes_a_failure_row(self):
        _, added, _ = _drive(_assignment(), _order())
        failure = added[0]
        assert failure.order_id == "ORD_1"
        assert failure.reason is DeliveryFailureReason.BUYER_UNAVAILABLE
        assert failure.report_notes == "No answer"
        assert failure.outcome is DeliveryFailureOutcome.PENDING

    def test_it_carries_no_run(self):
        # The same table as a run's failure, with delivery_run_id null --
        # which is what that nullable column is for.
        _, added, _ = _drive(_assignment(), _order())
        assert added[0].delivery_run_id is None

    def test_the_reporting_rider_is_recorded(self):
        _, added, _ = _drive(_assignment(), _order())
        assert added[0].reported_by_delivery_user_id == "DEL_1"


class TestItReleasesTheRider:
    def test_the_assignment_goes_to_failed(self):
        # Not REJECTED, which means declined before committing. FAILED
        # was added for this and was unreachable from this path.
        assignment = _assignment()
        _drive(assignment, _order())
        assert assignment.status is AssignmentStatus.FAILED

    def test_which_is_what_frees_the_slot(self):
        # get_active_assignments and the concurrency count both filter
        # on status == ACCEPTED, so FAILED is what drops this out of
        # "carrying" and lets the rider take another job.
        import inspect

        from app.deliveries.services import DeliveryService

        source = inspect.getsource(DeliveryService.get_active_assignments)
        assert "AssignmentStatus.ACCEPTED" in source


class TestWhatItRefuses:
    def test_a_delivery_that_is_not_theirs(self):
        with pytest.raises(NotFoundError):
            _drive(None, _order())

    def test_a_delivery_already_confirmed(self):
        # The code has been scanned and the rider has been paid. There
        # is nothing to report and nothing to release.
        with pytest.raises(ConflictError):
            _drive(_assignment(logistical_status=LogisticalStatus.COMPLETED), _order())


class TestTheBuyerIsTold:
    def test_they_get_a_notification(self):
        calls = []

        def notify(user_id, notification_type, **kwargs):
            calls.append((user_id, notification_type))

        _drive(_assignment(), _order("USR_BUYER"), notify=notify)
        assert calls and calls[0][0] == "USR_BUYER"

    def test_a_failed_notification_does_not_undo_the_report(self):
        # The rider has already left the door. Losing the record of
        # why would be worse than a missed push.
        def boom(*args, **kwargs):
            raise RuntimeError("push provider down")

        result, added, _ = _drive(_assignment(), _order(), notify=boom)
        assert added[0].reason is DeliveryFailureReason.BUYER_UNAVAILABLE

    def test_an_order_with_no_buyer_does_not_raise(self):
        order = _order()
        order.buyer = None
        _drive(_assignment(), order)
