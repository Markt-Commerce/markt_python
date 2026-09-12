"""Unit tests for rider pickup-per-seller-stop and per-order POD within
an accepted DeliveryRun (10.6, Phase 10)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.deliveries.models import (
    AssignmentStatus,
    DeliveryRunOrderPodStatus,
    DeliveryRunStatus,
    DeliveryRunStopStatus,
)
from app.deliveries.pickup import (
    DeliveryRunPickupService,
    DeliveryRunPodService,
    create_stops_for_run,
)
from app.libs.errors import ConflictError, NotFoundError, ValidationError
from app.orders.models import OrderItem, OrderStatus


def _query_side_effect(**by_name):
    def side_effect(model):
        m = MagicMock()
        name = getattr(model, "__name__", None)
        config = by_name.get(name)
        if config:
            config(m)
        return m

    return side_effect


def _make_item(id, status, seller_id):
    item = SimpleNamespace(id=id, status=status, seller_id=seller_id, delivered_at=None)
    item.transition_to = lambda new_status, _item=item: OrderItem.transition_to(
        _item, new_status
    )
    return item


# --- create_stops_for_run ---------------------------------------------------


def test_create_stops_for_run_creates_one_stop_per_distinct_seller():
    order1 = SimpleNamespace(
        id="ORD_1",
        items=[
            _make_item(1, OrderItem.Status.PROCESSING, seller_id=10),
            _make_item(2, OrderItem.Status.PROCESSING, seller_id=11),
        ],
    )
    order2 = SimpleNamespace(
        id="ORD_2",
        items=[
            _make_item(3, OrderItem.Status.PROCESSING, seller_id=10),
            _make_item(4, OrderItem.Status.CANCELLED, seller_id=12),
        ],
    )
    run_order1 = SimpleNamespace(order_id="ORD_1")
    run_order2 = SimpleNamespace(order_id="ORD_2")

    session = MagicMock()

    def stop_query(m):
        m.filter_by.return_value.count.return_value = 0

    def run_order_query(m):
        m.filter_by.return_value.all.return_value = [run_order1, run_order2]

    def order_query(m):
        m.get.side_effect = lambda oid: {"ORD_1": order1, "ORD_2": order2}.get(oid)

    session.query.side_effect = _query_side_effect(
        DeliveryRunStop=stop_query,
        DeliveryRunOrder=run_order_query,
        Order=order_query,
    )

    seller_ids = create_stops_for_run(session, "RUN_1")

    # seller 12's only item is cancelled -- no stop for it.
    assert set(seller_ids) == {10, 11}
    assert session.add.call_count == 2


def test_create_stops_for_run_is_idempotent():
    session = MagicMock()

    def stop_query(m):
        m.filter_by.return_value.count.return_value = 3

    session.query.side_effect = _query_side_effect(DeliveryRunStop=stop_query)

    result = create_stops_for_run(session, "RUN_1")

    assert result == []
    session.add.assert_not_called()


# --- arrive_at_stop ----------------------------------------------------------


def test_arrive_at_stop_success():
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    stop = SimpleNamespace(
        seller_id=10, status=DeliveryRunStopStatus.PENDING, arrived_at=None
    )
    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def stop_query(m):
        m.filter_by.return_value.first.return_value = stop

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query, DeliveryRunStop=stop_query
    )

    with patch("app.deliveries.pickup.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryRunPickupService.arrive_at_stop("DEL_1", "RUN_1", 10)

    assert result == {
        "delivery_run_id": "RUN_1",
        "seller_id": 10,
        "status": DeliveryRunStopStatus.ARRIVED.value,
    }
    assert stop.status == DeliveryRunStopStatus.ARRIVED
    assert stop.arrived_at is not None


def test_arrive_at_stop_raises_not_found_without_accepted_assignment():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    with patch("app.deliveries.pickup.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(NotFoundError):
            DeliveryRunPickupService.arrive_at_stop("DEL_1", "RUN_1", 10)


def test_arrive_at_stop_raises_conflict_when_not_pending():
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    stop = SimpleNamespace(seller_id=10, status=DeliveryRunStopStatus.PICKED_UP)
    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def stop_query(m):
        m.filter_by.return_value.first.return_value = stop

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query, DeliveryRunStop=stop_query
    )

    with patch("app.deliveries.pickup.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ConflictError):
            DeliveryRunPickupService.arrive_at_stop("DEL_1", "RUN_1", 10)


# --- confirm_pickup_at_stop --------------------------------------------------


def test_confirm_pickup_at_stop_ships_items_and_starts_run():
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.RIDER_ACCEPTED)
    run.transition_to = lambda new_status, _r=run: setattr(_r, "status", new_status)
    stop = SimpleNamespace(
        seller_id=10, status=DeliveryRunStopStatus.PENDING, picked_up_at=None
    )
    item_seller_10 = _make_item(1, OrderItem.Status.PROCESSING, seller_id=10)
    item_seller_11 = _make_item(2, OrderItem.Status.PROCESSING, seller_id=11)
    order = SimpleNamespace(id="ORD_1", items=[item_seller_10, item_seller_11])
    run_order = SimpleNamespace(
        order_id="ORD_1", pod_status=DeliveryRunOrderPodStatus.PENDING, qr_code=None
    )

    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def run_query(m):
        m.filter_by.return_value.first.return_value = run

    def stop_query(m):
        m.filter_by.return_value.first.return_value = stop
        # "remaining" count -- one other stop still pending, so pod isn't
        # issued yet in this test.
        m.filter.return_value.count.return_value = 1

    def run_order_query(m):
        m.filter_by.return_value.all.return_value = [run_order]

    def order_query(m):
        m.get.return_value = order

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query,
        DeliveryRun=run_query,
        DeliveryRunStop=stop_query,
        DeliveryRunOrder=run_order_query,
        Order=order_query,
    )

    with patch("app.deliveries.pickup.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryRunPickupService.confirm_pickup_at_stop("DEL_1", "RUN_1", 10)

    assert result["status"] == DeliveryRunStopStatus.PICKED_UP.value
    assert result["run_status"] == DeliveryRunStatus.PICKUP_IN_PROGRESS.value
    assert result["pod_issued_for_orders"] == []
    assert item_seller_10.status == OrderItem.Status.SHIPPED
    # Different seller's item is untouched by this stop's confirmation.
    assert item_seller_11.status == OrderItem.Status.PROCESSING
    assert stop.status == DeliveryRunStopStatus.PICKED_UP
    assert run.status == DeliveryRunStatus.PICKUP_IN_PROGRESS


def test_confirm_pickup_at_stop_issues_pod_when_last_stop_done():
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.PICKUP_IN_PROGRESS)
    run.transition_to = lambda new_status, _r=run: setattr(_r, "status", new_status)
    stop = SimpleNamespace(
        seller_id=10, status=DeliveryRunStopStatus.PENDING, picked_up_at=None
    )
    item = _make_item(1, OrderItem.Status.PROCESSING, seller_id=10)
    order = SimpleNamespace(id="ORD_1", items=[item])
    run_order = SimpleNamespace(
        order_id="ORD_1", pod_status=DeliveryRunOrderPodStatus.PENDING, qr_code=None
    )

    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def run_query(m):
        m.filter_by.return_value.first.return_value = run

    def stop_query(m):
        m.filter_by.return_value.first.return_value = stop
        # No stops remain pending -- last stop just finished.
        m.filter.return_value.count.return_value = 0

    def run_order_query(m):
        m.filter_by.return_value.all.return_value = [run_order]

    def order_query(m):
        m.get.return_value = order

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query,
        DeliveryRun=run_query,
        DeliveryRunStop=stop_query,
        DeliveryRunOrder=run_order_query,
        Order=order_query,
    )

    with patch("app.deliveries.pickup.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryRunPickupService.confirm_pickup_at_stop("DEL_1", "RUN_1", 10)

    assert result["run_status"] == DeliveryRunStatus.DELIVERY_IN_PROGRESS.value
    assert result["pod_issued_for_orders"] == ["ORD_1"]
    assert run_order.pod_status == DeliveryRunOrderPodStatus.QR_ISSUED
    assert run_order.qr_code is not None


def test_confirm_pickup_at_stop_raises_conflict_when_already_picked_up():
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.PICKUP_IN_PROGRESS)
    stop = SimpleNamespace(seller_id=10, status=DeliveryRunStopStatus.PICKED_UP)
    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def run_query(m):
        m.filter_by.return_value.first.return_value = run

    def stop_query(m):
        m.filter_by.return_value.first.return_value = stop

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query,
        DeliveryRun=run_query,
        DeliveryRunStop=stop_query,
    )

    with patch("app.deliveries.pickup.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ConflictError):
            DeliveryRunPickupService.confirm_pickup_at_stop("DEL_1", "RUN_1", 10)


# --- get_order_pod_qr ---------------------------------------------------------


def test_get_order_pod_qr_success():
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    run_order = SimpleNamespace(
        order_id="ORD_1",
        pod_status=DeliveryRunOrderPodStatus.QR_ISSUED,
        qr_code="QR123",
    )
    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def run_order_query(m):
        m.filter_by.return_value.first.return_value = run_order

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query, DeliveryRunOrder=run_order_query
    )

    with patch("app.deliveries.pickup.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryRunPodService.get_order_pod_qr("DEL_1", "RUN_1", "ORD_1")

    assert result == {"order_id": "ORD_1", "qr_code": "QR123"}


def test_get_order_pod_qr_raises_validation_when_not_ready():
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    run_order = SimpleNamespace(
        order_id="ORD_1", pod_status=DeliveryRunOrderPodStatus.PENDING, qr_code=None
    )
    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def run_order_query(m):
        m.filter_by.return_value.first.return_value = run_order

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query, DeliveryRunOrder=run_order_query
    )

    with patch("app.deliveries.pickup.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ValidationError):
            DeliveryRunPodService.get_order_pod_qr("DEL_1", "RUN_1", "ORD_1")


# --- confirm_order_pod --------------------------------------------------------


@patch("app.orders.services.OrderService.update_order_status")
def test_confirm_order_pod_marks_items_delivered_and_completes_run(mock_update):
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    run_order = SimpleNamespace(
        order_id="ORD_1",
        pod_status=DeliveryRunOrderPodStatus.QR_ISSUED,
        qr_code="QR123",
        delivered_at=None,
    )
    item_a = _make_item(1, OrderItem.Status.SHIPPED, seller_id=10)
    item_b = _make_item(2, OrderItem.Status.CANCELLED, seller_id=11)
    order = SimpleNamespace(id="ORD_1", items=[item_a, item_b])
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.DELIVERY_IN_PROGRESS)
    run.transition_to = lambda new_status, _r=run: setattr(_r, "status", new_status)

    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def run_order_first_query(m):
        m.filter_by.return_value.first.return_value = run_order
        # "remaining undelivered" count -- this is the only order, and
        # it's about to be delivered.
        m.filter.return_value.count.return_value = 0

    def order_query(m):
        m.get.return_value = order

    def run_query(m):
        m.filter_by.return_value.first.return_value = run

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query,
        DeliveryRunOrder=run_order_first_query,
        Order=order_query,
        DeliveryRun=run_query,
    )

    with patch("app.deliveries.pickup.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryRunPodService.confirm_order_pod(
            "DEL_1", "RUN_1", "ORD_1", "QR123"
        )

    assert result == {
        "status": "success",
        "message": "Order marked as delivered",
        "run_completed": True,
    }
    assert item_a.status == OrderItem.Status.DELIVERED
    assert item_a.delivered_at is not None
    # Cancelled item is left alone.
    assert item_b.status == OrderItem.Status.CANCELLED
    assert run_order.pod_status == DeliveryRunOrderPodStatus.DELIVERED
    assert run.status == DeliveryRunStatus.COMPLETED
    mock_update.assert_called_once_with("ORD_1", OrderStatus.DELIVERED)


def test_confirm_order_pod_raises_validation_for_wrong_qr_code():
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    run_order = SimpleNamespace(
        order_id="ORD_1",
        pod_status=DeliveryRunOrderPodStatus.QR_ISSUED,
        qr_code="QR123",
    )
    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def run_order_query(m):
        m.filter_by.return_value.first.return_value = run_order

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query, DeliveryRunOrder=run_order_query
    )

    with patch("app.deliveries.pickup.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ValidationError):
            DeliveryRunPodService.confirm_order_pod("DEL_1", "RUN_1", "ORD_1", "WRONG")
