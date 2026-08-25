"""Unit tests for FulfilmentService: seller accept/decline/timeout of an
item allocation (12.1-12.2)."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.fulfilment.models import FulfilmentAllocation, FulfilmentAllocationStatus
from app.fulfilment.services import FulfilmentService
from app.libs.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.orders.events import OrderEventType
from app.orders.models import FulfilmentPreference
from app.payments.models import PaymentStatus


def _allocation(status, **overrides):
    defaults = dict(id=1, order_item_id=10, seller_id=7, reservation_id=None)
    defaults.update(overrides)
    a = SimpleNamespace(status=status, **defaults)
    a.transition_to = lambda new_status, _a=a: FulfilmentAllocation.transition_to(
        _a, new_status
    )
    return a


@patch("app.fulfilment.services.NotificationService.create_notification")
@patch("app.fulfilment.services.session_scope")
def test_create_allocation_notifies_seller(mock_scope, mock_notify):
    order_item = SimpleNamespace(product_id="PRD_1", order_id="ORD_1")
    seller = SimpleNamespace(user_id="USR_SELLER1")
    fetched = SimpleNamespace(id=99)
    session = MagicMock()

    def add_side_effect(obj):
        obj.id = 99

    session.add.side_effect = add_side_effect
    # Call order: order_item lookup (product_id default), seller lookup,
    # then the second session_scope's re-fetch by id.
    session.query.return_value.get.side_effect = [order_item, seller, fetched]

    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.create_allocation(10, 7, 2)

    assert result is fetched
    mock_notify.assert_called_once()
    call_kwargs = mock_notify.call_args.kwargs
    assert call_kwargs["user_id"] == "USR_SELLER1"
    assert call_kwargs["reference_id"] == "99"

    # 14.2: the original (non-reroute) allocation emits ITEM_ALLOCATED,
    # not ITEM_REROUTED.
    emitted_event = session.add.call_args_list[1][0][0]
    assert emitted_event.event_type == OrderEventType.ITEM_ALLOCATED
    assert emitted_event.order_id == "ORD_1"


@patch("app.fulfilment.services.NotificationService.create_notification")
@patch("app.fulfilment.services.session_scope")
def test_create_allocation_skips_notification_when_seller_missing(
    mock_scope, mock_notify
):
    order_item = SimpleNamespace(product_id="PRD_1", order_id="ORD_1")
    session = MagicMock()
    session.query.return_value.get.side_effect = [
        order_item,
        None,
        SimpleNamespace(id=99),
    ]
    session.add.side_effect = lambda obj: setattr(obj, "id", 99)
    mock_scope.return_value.__enter__.return_value = session

    FulfilmentService.create_allocation(10, 7, 2)

    mock_notify.assert_not_called()


@patch("app.fulfilment.services.NotificationService.create_notification")
@patch("app.fulfilment.services.session_scope")
def test_create_allocation_uses_explicit_product_id_for_reroutes(
    mock_scope, mock_notify
):
    """A reroute-created allocation passes product_id explicitly (the
    replacement seller's own Product row) and must not use
    OrderItem.product_id's value -- OrderItem is still looked up (now
    unconditionally) for its order_id, needed for the 14.2 event log."""
    order_item = SimpleNamespace(product_id="PRD_ORIGINAL", order_id="ORD_1")
    seller = SimpleNamespace(user_id="USR_SELLER1")
    fetched = SimpleNamespace(id=99)
    session = MagicMock()
    session.add.side_effect = lambda obj: setattr(obj, "id", 99)
    session.query.return_value.get.side_effect = [order_item, seller, fetched]

    mock_scope.return_value.__enter__.return_value = session

    FulfilmentService.create_allocation(10, 7, 2, product_id="PRD_REPLACEMENT")

    # First add() call is the FulfilmentAllocation itself -- a second one
    # follows for the 14.2 OrderEvent this now also emits.
    added = session.add.call_args_list[0][0][0]
    assert added.product_id == "PRD_REPLACEMENT"

    # An explicit product_id is exactly the reroute signal -- ITEM_REROUTED,
    # not ITEM_ALLOCATED.
    emitted_event = session.add.call_args_list[1][0][0]
    assert emitted_event.event_type == OrderEventType.ITEM_REROUTED


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


def _accept_query_side_effect(fa_mock, oi_mock, product_mock):
    def side_effect(model):
        name = getattr(model, "__name__", None)
        if name == "FulfilmentAllocation":
            return fa_mock
        if name == "OrderItem":
            return oi_mock
        if name == "Product":
            return product_mock
        return MagicMock()

    return side_effect


@patch("app.fulfilment.services.NotificationService.create_notification")
@patch("app.fulfilment.services.session_scope")
def test_accept_gates_material_substitution_for_ask_preference(mock_scope, mock_notify):
    """6.1: an ASK buyer whose replacement seller's price differs from the
    original lands at AWAITING_BUYER_APPROVAL, not ACCEPTED, and is notified."""
    allocation = _allocation(
        FulfilmentAllocationStatus.AWAITING_SELLER, product_id="PRD_2"
    )
    order_item = SimpleNamespace(
        id=10,
        order_id="ORD_1",
        fulfilment_preference=FulfilmentPreference.ASK,
        price=1000.0,
        order=SimpleNamespace(buyer=SimpleNamespace(user_id="USR_BUYER1")),
    )
    product = SimpleNamespace(price=1040.0)

    fa_mock = MagicMock()
    fa_mock.filter_by.return_value.first.return_value = allocation
    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item
    product_mock = MagicMock()
    product_mock.get.return_value = product

    session = MagicMock()
    session.query.side_effect = _accept_query_side_effect(
        fa_mock, oi_mock, product_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.accept(1, seller_id=7)

    assert result.status == FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL
    mock_notify.assert_called_once()
    assert mock_notify.call_args.kwargs["user_id"] == "USR_BUYER1"


@patch("app.fulfilment.services.NotificationService.create_notification")
@patch("app.fulfilment.services.session_scope")
def test_accept_same_price_ask_proceeds_silently(mock_scope, mock_notify):
    """The spec's own non-material example: same price, different seller --
    proceeds straight to ACCEPTED even for an ASK buyer."""
    allocation = _allocation(
        FulfilmentAllocationStatus.AWAITING_SELLER, product_id="PRD_2"
    )
    order_item = SimpleNamespace(
        id=10,
        order_id="ORD_1",
        fulfilment_preference=FulfilmentPreference.ASK,
        price=1000.0,
        order=SimpleNamespace(buyer=SimpleNamespace(user_id="USR_BUYER1")),
    )
    product = SimpleNamespace(price=1000.0)

    fa_mock = MagicMock()
    fa_mock.filter_by.return_value.first.return_value = allocation
    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item
    product_mock = MagicMock()
    product_mock.get.return_value = product

    session = MagicMock()
    session.query.side_effect = _accept_query_side_effect(
        fa_mock, oi_mock, product_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.accept(1, seller_id=7)

    assert result.status == FulfilmentAllocationStatus.ACCEPTED
    mock_notify.assert_not_called()


@patch("app.fulfilment.services.NotificationService.create_notification")
@patch("app.fulfilment.services.session_scope")
def test_accept_auto_preference_ignores_price_difference(mock_scope, mock_notify):
    """The ASK gate only applies to ASK -- AUTO commits a material
    substitution silently, which is the whole point of AUTO."""
    allocation = _allocation(
        FulfilmentAllocationStatus.AWAITING_SELLER, product_id="PRD_2"
    )
    order_item = SimpleNamespace(
        id=10,
        order_id="ORD_1",
        fulfilment_preference=FulfilmentPreference.AUTO,
        price=1000.0,
        order=SimpleNamespace(buyer=SimpleNamespace(user_id="USR_BUYER1")),
    )
    product = SimpleNamespace(price=1040.0)

    fa_mock = MagicMock()
    fa_mock.filter_by.return_value.first.return_value = allocation
    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item
    product_mock = MagicMock()
    product_mock.get.return_value = product

    session = MagicMock()
    session.query.side_effect = _accept_query_side_effect(
        fa_mock, oi_mock, product_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.accept(1, seller_id=7)

    assert result.status == FulfilmentAllocationStatus.ACCEPTED
    mock_notify.assert_not_called()


@patch("app.fulfilment.rerouting.ReroutingService.attempt_reroute")
@patch("app.fulfilment.services.session_scope")
def test_cancel_after_accept_transitions_to_cancelled_by_seller(
    mock_scope, mock_reroute
):
    allocation = _allocation(FulfilmentAllocationStatus.ACCEPTED)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = allocation
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.cancel_after_accept(1, seller_id=7)

    assert result.status == FulfilmentAllocationStatus.CANCELLED_BY_SELLER


@patch("app.fulfilment.rerouting.ReroutingService.attempt_reroute")
@patch("app.fulfilment.services.session_scope")
def test_cancel_after_accept_allowed_from_preparing(mock_scope, mock_reroute):
    allocation = _allocation(FulfilmentAllocationStatus.PREPARING)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = allocation
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.cancel_after_accept(1, seller_id=7)

    assert result.status == FulfilmentAllocationStatus.CANCELLED_BY_SELLER


@patch("app.fulfilment.rerouting.ReroutingService.attempt_reroute")
@patch("app.inventory.services.InventoryService.release_reservations")
@patch("app.fulfilment.services.session_scope")
def test_cancel_after_accept_releases_reservation_and_reroutes(
    mock_scope, mock_release, mock_reroute
):
    allocation = _allocation(
        FulfilmentAllocationStatus.ACCEPTED, reservation_id="RSV_1"
    )
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = allocation
    mock_scope.return_value.__enter__.return_value = session

    FulfilmentService.cancel_after_accept(1, seller_id=7)

    mock_release.assert_called_once_with(["RSV_1"])
    mock_reroute.assert_called_once_with(1)


@patch("app.fulfilment.services.session_scope")
def test_cancel_after_accept_raises_not_found_for_missing_allocation(mock_scope):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(NotFoundError):
        FulfilmentService.cancel_after_accept(1, seller_id=7)


@patch("app.fulfilment.services.session_scope")
def test_cancel_after_accept_rejects_from_awaiting_seller(mock_scope):
    """Only a seller who has actually accepted can "accept-then-cancel" --
    an AWAITING_SELLER allocation should use decline() instead."""
    allocation = _allocation(FulfilmentAllocationStatus.AWAITING_SELLER)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = allocation
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ValueError):
        FulfilmentService.cancel_after_accept(1, seller_id=7)


@patch("app.fulfilment.services.session_scope")
def test_buyer_approve_reroute_transitions_to_accepted(mock_scope):
    allocation = _allocation(FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL)
    order_item = SimpleNamespace(
        id=10, order_id="ORD_1", order=SimpleNamespace(buyer_id="BYR_1")
    )

    fa_mock = MagicMock()
    fa_mock.filter_by.return_value.first.return_value = allocation
    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    session = MagicMock()
    session.query.side_effect = _accept_query_side_effect(fa_mock, oi_mock, MagicMock())
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.buyer_approve_reroute(1, buyer_id="BYR_1")

    assert result.status == FulfilmentAllocationStatus.ACCEPTED


@patch("app.fulfilment.services.session_scope")
def test_buyer_approve_reroute_raises_forbidden_for_wrong_buyer(mock_scope):
    allocation = _allocation(FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL)
    order_item = SimpleNamespace(
        id=10, order_id="ORD_1", order=SimpleNamespace(buyer_id="BYR_1")
    )

    fa_mock = MagicMock()
    fa_mock.filter_by.return_value.first.return_value = allocation
    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    session = MagicMock()
    session.query.side_effect = _accept_query_side_effect(fa_mock, oi_mock, MagicMock())
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ForbiddenError):
        FulfilmentService.buyer_approve_reroute(1, buyer_id="BYR_OTHER")


@patch("app.fulfilment.rerouting.ReroutingService.attempt_reroute")
@patch("app.inventory.services.InventoryService.release_reservations")
@patch("app.fulfilment.services.session_scope")
def test_buyer_reject_reroute_releases_reservation_and_retries(
    mock_scope, mock_release, mock_reroute
):
    allocation = _allocation(
        FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL, reservation_id="RSV_1"
    )
    order_item = SimpleNamespace(
        id=10, order_id="ORD_1", order=SimpleNamespace(buyer_id="BYR_1")
    )

    fa_mock = MagicMock()
    fa_mock.filter_by.return_value.first.return_value = allocation
    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    session = MagicMock()
    session.query.side_effect = _accept_query_side_effect(fa_mock, oi_mock, MagicMock())
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.buyer_reject_reroute(1, buyer_id="BYR_1")

    assert result.status == FulfilmentAllocationStatus.BUYER_REJECTED
    mock_release.assert_called_once_with(["RSV_1"])
    mock_reroute.assert_called_once_with(1)


@patch("app.fulfilment.rerouting.ReroutingService.attempt_reroute")
@patch("app.fulfilment.services.session_scope")
def test_decline_stops_at_declined(mock_scope, mock_reroute):
    allocation = _allocation(FulfilmentAllocationStatus.AWAITING_SELLER)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = allocation
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.decline(1, seller_id=7)

    assert result.status == FulfilmentAllocationStatus.DECLINED


@patch("app.fulfilment.rerouting.ReroutingService.attempt_reroute")
@patch("app.inventory.services.InventoryService.release_reservations")
@patch("app.fulfilment.services.session_scope")
def test_decline_releases_reservation_when_present(
    mock_scope, mock_release, mock_reroute
):
    allocation = _allocation(
        FulfilmentAllocationStatus.AWAITING_SELLER, reservation_id="RSV_1"
    )
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = allocation
    mock_scope.return_value.__enter__.return_value = session

    FulfilmentService.decline(1, seller_id=7)

    mock_release.assert_called_once_with(["RSV_1"])


@patch("app.fulfilment.rerouting.ReroutingService.attempt_reroute")
@patch("app.inventory.services.InventoryService.release_reservations")
@patch("app.fulfilment.services.session_scope")
def test_decline_skips_release_without_reservation(
    mock_scope, mock_release, mock_reroute
):
    allocation = _allocation(FulfilmentAllocationStatus.AWAITING_SELLER)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = allocation
    mock_scope.return_value.__enter__.return_value = session

    FulfilmentService.decline(1, seller_id=7)

    mock_release.assert_not_called()


@patch("app.fulfilment.rerouting.ReroutingService.attempt_reroute")
@patch("app.fulfilment.services.session_scope")
def test_decline_triggers_reroute_attempt(mock_scope, mock_reroute):
    allocation = _allocation(FulfilmentAllocationStatus.AWAITING_SELLER)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = allocation
    mock_scope.return_value.__enter__.return_value = session

    FulfilmentService.decline(1, seller_id=7)

    mock_reroute.assert_called_once_with(1)


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


@patch("app.fulfilment.rerouting.ReroutingService.attempt_reroute")
@patch("app.fulfilment.services.session_scope")
def test_expire_stale_allocations_times_out_past_deadline(mock_scope, mock_reroute):
    allocation = _allocation(
        FulfilmentAllocationStatus.AWAITING_SELLER,
        seller_response_deadline=datetime.utcnow() - timedelta(minutes=1),
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [allocation]
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.expire_stale_allocations()

    assert result == {"timed_out": 1}
    assert allocation.status == FulfilmentAllocationStatus.TIMEOUT


@patch("app.fulfilment.rerouting.ReroutingService.attempt_reroute")
@patch("app.inventory.services.InventoryService.release_reservations")
@patch("app.fulfilment.services.session_scope")
def test_expire_stale_allocations_releases_reservations(
    mock_scope, mock_release, mock_reroute
):
    allocation = _allocation(
        FulfilmentAllocationStatus.AWAITING_SELLER,
        seller_response_deadline=datetime.utcnow() - timedelta(minutes=1),
        reservation_id="RSV_1",
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [allocation]
    mock_scope.return_value.__enter__.return_value = session

    FulfilmentService.expire_stale_allocations()

    mock_release.assert_called_once_with(["RSV_1"])


@patch("app.fulfilment.rerouting.ReroutingService.attempt_reroute")
@patch("app.fulfilment.services.session_scope")
def test_expire_stale_allocations_triggers_reroute_attempt(mock_scope, mock_reroute):
    allocation = _allocation(
        FulfilmentAllocationStatus.AWAITING_SELLER,
        seller_response_deadline=datetime.utcnow() - timedelta(minutes=1),
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [allocation]
    mock_scope.return_value.__enter__.return_value = session

    FulfilmentService.expire_stale_allocations()

    mock_reroute.assert_called_once_with(1)


@patch("app.fulfilment.services.session_scope")
def test_expire_stale_allocations_no_op_when_none_stale(mock_scope):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.expire_stale_allocations()

    assert result == {"timed_out": 0}


@patch("app.fulfilment.rerouting.ReroutingService.attempt_reroute")
@patch("app.orders.services.OrderService.refund_unresolved_item")
@patch("app.inventory.services.InventoryService.release_reservations")
@patch("app.fulfilment.services.session_scope")
def test_expire_stale_buyer_approvals_times_out_and_refunds(
    mock_scope, mock_release, mock_refund, mock_reroute
):
    allocation = _allocation(
        FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL, reservation_id="RSV_1"
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [allocation]
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.expire_stale_buyer_approvals()

    assert result == {"timed_out": 1}
    assert allocation.status == FulfilmentAllocationStatus.UNFULFILLED
    mock_release.assert_called_once_with(["RSV_1"])
    mock_refund.assert_called_once()
    assert mock_refund.call_args.args[0] == allocation.order_item_id
    # 9.1: no substitution retry on an ASK timeout, unlike decline/timeout.
    mock_reroute.assert_not_called()


@patch("app.orders.services.OrderService.refund_unresolved_item")
@patch("app.inventory.services.InventoryService.release_reservations")
@patch("app.fulfilment.services.session_scope")
def test_expire_stale_buyer_approvals_skips_release_without_reservation(
    mock_scope, mock_release, mock_refund
):
    allocation = _allocation(FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [allocation]
    mock_scope.return_value.__enter__.return_value = session

    FulfilmentService.expire_stale_buyer_approvals()

    mock_release.assert_not_called()
    mock_refund.assert_called_once()


@patch("app.orders.services.OrderService.refund_unresolved_item")
@patch("app.fulfilment.services.session_scope")
def test_expire_stale_buyer_approvals_no_op_when_none_stale(mock_scope, mock_refund):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.expire_stale_buyer_approvals()

    assert result == {"timed_out": 0}
    mock_refund.assert_not_called()


# ---- list_seller_allocations ----


@patch("app.fulfilment.services.session_scope")
def test_list_seller_allocations_defaults_to_active_statuses(mock_scope):
    expected = [SimpleNamespace(id=1)]
    session = MagicMock()
    active_query = (
        session.query.return_value.options.return_value.filter_by.return_value
    )
    active_query.filter.return_value.order_by.return_value.all.return_value = expected
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.list_seller_allocations(7)

    assert result == expected
    active_query.filter.assert_called_once()
    active_query.filter_by.assert_not_called()


@patch("app.fulfilment.services.session_scope")
def test_list_seller_allocations_filters_by_explicit_status(mock_scope):
    expected = [SimpleNamespace(id=2)]
    session = MagicMock()
    base_query = session.query.return_value.options.return_value.filter_by.return_value
    base_query.filter_by.return_value.order_by.return_value.all.return_value = expected
    mock_scope.return_value.__enter__.return_value = session

    result = FulfilmentService.list_seller_allocations(7, status="timeout")

    assert result == expected
    base_query.filter_by.assert_called_once_with(
        status=FulfilmentAllocationStatus.TIMEOUT
    )
    base_query.filter.assert_not_called()


@patch("app.fulfilment.services.session_scope")
def test_list_seller_allocations_rejects_unknown_status(mock_scope):
    session = MagicMock()
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ValidationError):
        FulfilmentService.list_seller_allocations(7, status="not_a_real_status")
