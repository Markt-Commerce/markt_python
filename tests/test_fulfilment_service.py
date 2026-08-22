"""Unit tests for FulfilmentService: seller accept/decline/timeout of an
item allocation (§12.1-12.2)."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.fulfilment.models import FulfilmentAllocation, FulfilmentAllocationStatus
from app.fulfilment.services import FulfilmentService
from app.libs.errors import ConflictError, NotFoundError
from app.payments.models import PaymentStatus


def _allocation(status, **overrides):
    a = SimpleNamespace(
        id=1,
        order_item_id=10,
        seller_id=7,
        status=status,
        **overrides,
    )
    a.transition_to = lambda new_status, _a=a: FulfilmentAllocation.transition_to(
        _a, new_status
    )
    return a


@patch("app.fulfilment.services.NotificationService.create_notification")
@patch("app.fulfilment.services.session_scope")
def test_create_allocation_notifies_seller(mock_scope, mock_notify):
    seller = SimpleNamespace(user_id="USR_SELLER1")
    session = MagicMock()
    session.query.return_value.get.return_value = seller

    def add_side_effect(obj):
        obj.id = 99

    session.add.side_effect = add_side_effect

    fetched = SimpleNamespace(id=99)
    # Second session_scope call (re-fetch by id) returns the same object.
    session.query.return_value.get.side_effect = [seller, fetched]

    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.create_allocation(10, 7, 2)

    assert result is fetched
    mock_notify.assert_called_once()
    call_kwargs = mock_notify.call_args.kwargs
    assert call_kwargs["user_id"] == "USR_SELLER1"
    assert call_kwargs["reference_id"] == "99"


@patch("app.fulfilment.services.NotificationService.create_notification")
@patch("app.fulfilment.services.session_scope")
def test_create_allocation_skips_notification_when_seller_missing(
    mock_scope, mock_notify
):
    session = MagicMock()
    session.query.return_value.get.side_effect = [None, SimpleNamespace(id=99)]
    session.add.side_effect = lambda obj: setattr(obj, "id", 99)
    mock_scope.return_value.__enter__.return_value = session

    FulfilmentService.create_allocation(10, 7, 2)

    mock_notify.assert_not_called()


@patch("app.fulfilment.services.session_scope")
def test_accept_transitions_to_accepted(mock_scope):
    allocation = _allocation(FulfilmentAllocationStatus.AWAITING_SELLER)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = allocation
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.accept(1, seller_id=7)

    assert result.status == FulfilmentAllocationStatus.ACCEPTED


@patch("app.fulfilment.services.session_scope")
def test_accept_raises_not_found_for_missing_allocation(mock_scope):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(NotFoundError):
        FulfilmentService.accept(1, seller_id=7)


@patch("app.fulfilment.services.session_scope")
def test_decline_routes_through_to_rerouting(mock_scope):
    allocation = _allocation(FulfilmentAllocationStatus.AWAITING_SELLER)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = allocation
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.decline(1, seller_id=7)

    assert result.status == FulfilmentAllocationStatus.REROUTING


@patch("app.fulfilment.services.session_scope")
def test_start_preparing_requires_completed_payment(mock_scope):
    payment = SimpleNamespace(status=PaymentStatus.PENDING)
    order = SimpleNamespace(payments=[payment])
    order_item = SimpleNamespace(order=order)
    allocation = _allocation(FulfilmentAllocationStatus.ACCEPTED, order_item=order_item)

    session = MagicMock()
    session.query.return_value.options.return_value.filter_by.return_value.first.return_value = (
        allocation
    )
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ConflictError):
        FulfilmentService.start_preparing(1, seller_id=7)

    assert allocation.status == FulfilmentAllocationStatus.ACCEPTED


@patch("app.fulfilment.services.session_scope")
def test_start_preparing_succeeds_with_completed_payment(mock_scope):
    payment = SimpleNamespace(status=PaymentStatus.COMPLETED)
    order = SimpleNamespace(payments=[payment])
    order_item = SimpleNamespace(order=order)
    allocation = _allocation(FulfilmentAllocationStatus.ACCEPTED, order_item=order_item)

    session = MagicMock()
    session.query.return_value.options.return_value.filter_by.return_value.first.return_value = (
        allocation
    )
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.start_preparing(1, seller_id=7)

    assert result.status == FulfilmentAllocationStatus.PREPARING


@patch("app.fulfilment.services.session_scope")
def test_expire_stale_allocations_times_out_past_deadline(mock_scope):
    allocation = _allocation(
        FulfilmentAllocationStatus.AWAITING_SELLER,
        seller_response_deadline=datetime.utcnow() - timedelta(minutes=1),
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [allocation]
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.expire_stale_allocations()

    assert result == {"timed_out": 1}
    assert allocation.status == FulfilmentAllocationStatus.REROUTING


@patch("app.fulfilment.services.session_scope")
def test_expire_stale_allocations_no_op_when_none_stale(mock_scope):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.expire_stale_allocations()

    assert result == {"timed_out": 0}
