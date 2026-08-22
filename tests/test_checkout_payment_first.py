"""Unit tests for the payment-first checkout flow (Phase 4 decision):
reserve stock -> pay -> create the Order only on payment success. This is
an ADDITIVE alternative to the existing order-first CartService.checkout_cart
flow, which these tests don't touch."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.inventory.models import InventoryReservation
from app.inventory.services import InventoryService
from app.libs.errors import ConflictError, ValidationError
from app.orders.models import Order, OrderItem, OrderStatus
from app.orders.services import OrderService
from app.payments.models import Payment, PaymentMethod, PaymentStatus
from app.payments.services import PaymentService


def _reservation(id_, status=InventoryReservation.Status.HELD):
    r = InventoryReservation()
    r.id = id_
    r.status = status
    return r


# ---------------------------------------------------------------------------
# InventoryService.confirm_reservations / release_reservations
# ---------------------------------------------------------------------------


def test_confirm_reservations_promotes_held_to_confirmed_and_sets_order():
    reservation = _reservation("RSV_1", InventoryReservation.Status.HELD)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [reservation]

    InventoryService.confirm_reservations(session, ["RSV_1"], "ORD_1")

    assert reservation.status == InventoryReservation.Status.CONFIRMED
    assert reservation.order_id == "ORD_1"


def test_confirm_reservations_promotes_requested_through_held_to_confirmed():
    reservation = _reservation("RSV_1", InventoryReservation.Status.REQUESTED)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [reservation]

    InventoryService.confirm_reservations(session, ["RSV_1"], "ORD_1")

    assert reservation.status == InventoryReservation.Status.CONFIRMED


def test_confirm_reservations_is_idempotent_for_already_confirmed():
    reservation = _reservation("RSV_1", InventoryReservation.Status.CONFIRMED)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [reservation]

    InventoryService.confirm_reservations(session, ["RSV_1"], "ORD_1")

    assert reservation.status == InventoryReservation.Status.CONFIRMED
    assert reservation.order_id == "ORD_1"


def test_confirm_reservations_no_op_for_empty_list():
    session = MagicMock()
    InventoryService.confirm_reservations(session, [], "ORD_1")
    session.query.assert_not_called()


@patch("app.inventory.services.session_scope")
def test_release_reservations_releases_held_and_requested(mock_scope):
    held = _reservation("RSV_1", InventoryReservation.Status.HELD)
    requested = _reservation("RSV_2", InventoryReservation.Status.REQUESTED)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [held, requested]
    mock_scope.return_value.__enter__.return_value = session

    InventoryService.release_reservations(["RSV_1", "RSV_2"])

    assert held.status == InventoryReservation.Status.RELEASED
    assert requested.status == InventoryReservation.Status.RELEASED


@patch("app.inventory.services.session_scope")
def test_release_reservations_skips_terminal_states(mock_scope):
    consumed = _reservation("RSV_1", InventoryReservation.Status.CONSUMED)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [consumed]
    mock_scope.return_value.__enter__.return_value = session

    InventoryService.release_reservations(["RSV_1"])

    assert consumed.status == InventoryReservation.Status.CONSUMED


# ---------------------------------------------------------------------------
# OrderService.create_order_from_checkout_snapshot
# ---------------------------------------------------------------------------


def test_create_order_from_checkout_snapshot_builds_paid_order():
    snapshot = {
        "items": [
            {
                "product_id": "PRD_1",
                "variant_id": None,
                "seller_id": 7,
                "quantity": 2,
                "price": 500.0,
                "reservation_id": "RSV_1",
            }
        ],
        "shipping_address": {
            "recipient_name": "Ada",
            "street_address": "1 Main St",
            "city": "Lagos",
            "state": "Lagos",
            "postal_code": "100001",
            "country": "Nigeria",
            "latitude": 6.5,
            "longitude": 3.4,
        },
        "subtotal": 1000.0,
        "shipping_fee": 100.0,
        "service_fee": 25.0,
        "reliability_fee_opted_in": True,
        "reliability_fee_estimate": 100.0,
        "capture_ceiling": 1275.0,
        "total": 1125.0,
    }
    session = MagicMock()

    def add_side_effect(obj):
        if isinstance(obj, Order) and obj.id is None:
            obj.id = "ORD_TEST01"

    session.add.side_effect = add_side_effect

    order = OrderService.create_order_from_checkout_snapshot(session, snapshot, 42)

    assert order.buyer_id == 42
    assert order.status == OrderStatus.READY_FOR_DELIVERY
    assert order.total == 1125.0
    assert order.service_fee == 25.0
    assert order.reliability_fee_opted_in is True
    assert order.reliability_fee_estimate == 100.0
    assert len(order.items) == 1
    assert order.items[0].status == OrderItem.Status.PROCESSING
    assert order.items[0].quantity == 2
    assert order.items[0].seller_id == 7
    # order, shipping address, order item, 14.2 ORDER_CREATED event
    assert session.add.call_count == 4


# ---------------------------------------------------------------------------
# PaymentService.initialize_checkout_payment
# ---------------------------------------------------------------------------


def _checkout_session(*, buyer=None, cart=None):
    session = MagicMock()

    def query_side_effect(*args):
        model = args[0]
        name = getattr(model, "__name__", None)
        mock = MagicMock()
        if name == "Buyer":
            mock.options.return_value.get.return_value = buyer
        elif name == "Payment":
            mock.filter_by.return_value.first.return_value = None
        elif name == "Cart":
            mock.filter_by.return_value.first.return_value = cart
        return mock

    session.query.side_effect = query_side_effect
    return session


@patch(
    "app.payments.services.PaymentService._initialize_paystack_transaction_for_checkout"
)
@patch.object(InventoryService, "reserve_stock")
@patch("app.cart.services.CartService._validate_cart_items")
def test_initialize_checkout_payment_reserves_each_item_and_snapshots_cart(
    mock_validate, mock_reserve, mock_paystack
):
    seller_product = SimpleNamespace(seller_id=7)
    cart_item = SimpleNamespace(
        product_id="PRD_1",
        variant_id=None,
        quantity=2,
        product_price=500.0,
        product=seller_product,
    )
    cart = SimpleNamespace(items=[cart_item], coupon_code=None, subtotal=lambda: 1000.0)
    buyer = SimpleNamespace(
        id=42,
        shipping_address=None,
        user=SimpleNamespace(email="buyer@example.com"),
    )
    mock_reserve.return_value = SimpleNamespace(id="RSV_1")

    session = _checkout_session(buyer=buyer, cart=cart)

    with patch("app.payments.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        payment = PaymentService.initialize_checkout_payment(
            42,
            {
                "shipping_address": {
                    "recipient_name": "Ada",
                    "street_address": "1 Main St",
                    "city": "Lagos",
                    "state": "Lagos",
                    "postal_code": "100001",
                    "country": "Nigeria",
                    "latitude": 6.5,
                    "longitude": 3.4,
                }
            },
        )

    mock_reserve.assert_called_once_with("PRD_1", 42, 2, variant_id=None)
    assert payment.buyer_id == 42
    assert payment.order_id is None
    assert payment.pending_checkout_data["items"][0]["reservation_id"] == "RSV_1"
    # subtotal=1000 + shipping_fee(flat 10.00 placeholder) + service_fee(2.5% of 1000 = 25)
    assert payment.pending_checkout_data["total"] == 1035.0
    assert payment.pending_checkout_data["service_fee"] == 25.0
    assert payment.pending_checkout_data["reliability_fee_opted_in"] is False
    assert payment.pending_checkout_data["reliability_fee_estimate"] == 0.0
    mock_paystack.assert_called_once()


@patch.object(InventoryService, "release_reservations")
@patch.object(InventoryService, "reserve_stock")
@patch("app.cart.services.CartService._validate_cart_items")
def test_initialize_checkout_payment_releases_reservations_on_partial_failure(
    mock_validate, mock_reserve, mock_release
):
    item_a = SimpleNamespace(
        product_id="PRD_1",
        variant_id=None,
        quantity=1,
        product_price=500.0,
        product=SimpleNamespace(seller_id=7),
    )
    item_b = SimpleNamespace(
        product_id="PRD_2",
        variant_id=None,
        quantity=1,
        product_price=500.0,
        product=SimpleNamespace(seller_id=7),
    )
    cart = SimpleNamespace(
        items=[item_a, item_b], coupon_code=None, subtotal=lambda: 1000.0
    )
    buyer = SimpleNamespace(
        id=42, shipping_address=None, user=SimpleNamespace(email="buyer@example.com")
    )
    mock_reserve.side_effect = [
        SimpleNamespace(id="RSV_1"),
        ConflictError("Only 0 unit(s) available"),
    ]

    session = _checkout_session(buyer=buyer, cart=cart)

    with patch("app.payments.services.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ConflictError):
            PaymentService.initialize_checkout_payment(
                42,
                {
                    "shipping_address": {
                        "recipient_name": "Ada",
                        "street_address": "1 Main St",
                        "city": "Lagos",
                        "state": "Lagos",
                        "postal_code": "100001",
                        "country": "Nigeria",
                        "latitude": 6.5,
                        "longitude": 3.4,
                    }
                },
            )

    mock_release.assert_called_once_with(["RSV_1"])


@patch("app.payments.services.session_scope")
def test_initialize_checkout_payment_is_idempotent(mock_scope):
    existing = SimpleNamespace(id="PAY_EXISTING")
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = existing
    mock_scope.return_value.__enter__.return_value = session

    result = PaymentService.initialize_checkout_payment(
        42, {"shipping_address": {}}, idempotency_key="idem-1"
    )

    assert result is existing


# ---------------------------------------------------------------------------
# PaymentService.complete_checkout_payment
# ---------------------------------------------------------------------------


def _payment(
    *, status=PaymentStatus.PENDING, order_id=None, snapshot=None, buyer_id=42
):
    p = SimpleNamespace(
        id="PAY_1",
        status=status,
        order_id=order_id,
        buyer_id=buyer_id,
        pending_checkout_data=snapshot,
        transaction_id="ref-1",
        paid_at=None,
        gateway_response={},
    )
    p.transition_to = lambda new_status, _p=p: Payment.transition_to(_p, new_status)
    return p


@patch("app.fulfilment.services.FulfilmentService.create_allocation")
@patch("app.orders.services.OrderService.create_order_from_checkout_snapshot")
@patch("app.inventory.services.InventoryService.confirm_reservations")
@patch("app.payments.services.PaymentService._invalidate_payment_cache")
@patch("app.payments.services.session_scope")
def test_complete_checkout_payment_builds_order_and_confirms_reservations(
    mock_scope, mock_invalidate, mock_confirm, mock_create_order, mock_create_allocation
):
    snapshot = {
        "items": [{"reservation_id": "RSV_1"}, {"reservation_id": "RSV_2"}],
    }
    payment = _payment(snapshot=snapshot)
    order_item = SimpleNamespace(id=1, seller_id=7, quantity=2, product_id="PRD_1")
    order = SimpleNamespace(id="ORD_1", items=[order_item])
    mock_create_order.return_value = order

    session = MagicMock()
    session.query.return_value.with_for_update.return_value.filter_by.return_value.first.return_value = (
        payment
    )
    session.query.return_value.filter_by.return_value.first.return_value = None  # cart
    mock_scope.return_value.__enter__.return_value = session

    result = PaymentService.complete_checkout_payment(payment_id="PAY_1")

    assert result is True
    assert payment.status == PaymentStatus.COMPLETED
    assert payment.order_id == "ORD_1"
    mock_confirm.assert_called_once_with(session, ["RSV_1", "RSV_2"], "ORD_1")
    mock_create_allocation.assert_called_once_with(1, 7, 2, product_id="PRD_1")


@patch("app.orders.services.OrderService.create_order_from_checkout_snapshot")
@patch("app.payments.services.PaymentService._invalidate_payment_cache")
@patch("app.payments.services.session_scope")
def test_complete_checkout_payment_is_idempotent_when_order_already_built(
    mock_scope, mock_invalidate, mock_create_order
):
    payment = _payment(
        status=PaymentStatus.COMPLETED, order_id="ORD_1", snapshot={"items": []}
    )
    session = MagicMock()
    session.query.return_value.with_for_update.return_value.filter_by.return_value.first.return_value = (
        payment
    )
    mock_scope.return_value.__enter__.return_value = session

    result = PaymentService.complete_checkout_payment(payment_id="PAY_1")

    assert result is True
    mock_create_order.assert_not_called()


@patch("app.payments.services.PaymentService._invalidate_payment_cache")
@patch("app.payments.services.session_scope")
def test_complete_checkout_payment_handles_missing_snapshot_gracefully(
    mock_scope, mock_invalidate
):
    payment = _payment(snapshot=None)
    session = MagicMock()
    session.query.return_value.with_for_update.return_value.filter_by.return_value.first.return_value = (
        payment
    )
    mock_scope.return_value.__enter__.return_value = session

    result = PaymentService.complete_checkout_payment(payment_id="PAY_1")

    assert result is True
    assert payment.status == PaymentStatus.COMPLETED
    assert payment.order_id is None


def test_complete_checkout_payment_returns_false_without_identifiers():
    assert PaymentService.complete_checkout_payment() is False


# ---------------------------------------------------------------------------
# Webhook / verify dispatch to the checkout-payment completion path
# ---------------------------------------------------------------------------


@patch("app.payments.services.PaymentService.complete_checkout_payment")
@patch("app.payments.services.PaymentService.complete_payment")
def test_handle_successful_charge_routes_checkout_type_to_checkout_completion(
    mock_complete_payment, mock_complete_checkout
):
    data = {"reference": "PAY_1", "metadata": {"type": "checkout"}}
    assert (
        PaymentService._handle_successful_charge(data)
        is mock_complete_checkout.return_value
    )
    mock_complete_checkout.assert_called_once_with(
        reference="PAY_1", gateway_response=data
    )
    mock_complete_payment.assert_not_called()


@patch("app.inventory.services.InventoryService.release_reservations")
@patch("app.payments.services.PaymentService._emit_payment_update")
@patch("app.payments.services.PaymentService._send_payment_notifications")
@patch("app.payments.services.session_scope")
def test_handle_failed_charge_releases_checkout_reservations(
    mock_scope, mock_notify, mock_emit, mock_release
):
    payment = _payment(
        status=PaymentStatus.PENDING,
        snapshot={"items": [{"reservation_id": "RSV_1"}, {"reservation_id": "RSV_2"}]},
    )
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = payment
    mock_scope.return_value.__enter__.return_value = session

    result = PaymentService._handle_failed_charge({"reference": "ref-1"})

    assert result is True
    assert payment.status == PaymentStatus.FAILED
    mock_release.assert_called_once_with(["RSV_1", "RSV_2"])


@patch("app.inventory.services.InventoryService.release_reservations")
@patch("app.payments.services.PaymentService._emit_payment_update")
@patch("app.payments.services.PaymentService._send_payment_notifications")
@patch("app.payments.services.session_scope")
def test_handle_failed_charge_is_idempotent_for_repeat_notifications(
    mock_scope, mock_notify, mock_emit, mock_release
):
    payment = _payment(
        status=PaymentStatus.FAILED,
        snapshot={"items": [{"reservation_id": "RSV_1"}]},
    )
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = payment
    mock_scope.return_value.__enter__.return_value = session

    PaymentService._handle_failed_charge({"reference": "ref-1"})

    mock_release.assert_not_called()


@patch("app.payments.services.PaymentService.complete_checkout_payment")
@patch("app.payments.services.PaymentService.complete_payment")
def test_handle_successful_charge_routes_order_based_payment_as_before(
    mock_complete_payment, mock_complete_checkout
):
    data = {"reference": "PAY_1", "metadata": {}}
    PaymentService._handle_successful_charge(data)
    mock_complete_payment.assert_called_once_with(
        reference="PAY_1", gateway_response=data
    )
    mock_complete_checkout.assert_not_called()


@patch("app.payments.services.requests.get")
@patch("app.payments.services.PaymentService.complete_checkout_payment")
@patch("app.payments.services.PaymentService.complete_payment")
@patch("app.payments.services.session_scope")
def test_verify_payment_routes_checkout_payment_to_checkout_completion(
    mock_scope, mock_complete_payment, mock_complete_checkout, mock_get
):
    payment = _payment(snapshot={"items": []})
    session = MagicMock()
    session.query.return_value.get.return_value = payment
    mock_scope.return_value.__enter__.return_value = session
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"status": True, "data": {"status": "success", "amount": 100}},
    )

    PaymentService.verify_payment("PAY_1")

    mock_complete_checkout.assert_called_once()
    mock_complete_payment.assert_not_called()


@patch("app.payments.services.requests.get")
@patch("app.payments.services.PaymentService.complete_checkout_payment")
@patch("app.payments.services.PaymentService.complete_payment")
@patch("app.payments.services.session_scope")
def test_verify_payment_routes_order_based_payment_as_before(
    mock_scope, mock_complete_payment, mock_complete_checkout, mock_get
):
    payment = _payment(snapshot=None)
    session = MagicMock()
    session.query.return_value.get.return_value = payment
    mock_scope.return_value.__enter__.return_value = session
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"status": True, "data": {"status": "success", "amount": 100}},
    )

    PaymentService.verify_payment("PAY_1")

    mock_complete_payment.assert_called_once()
    mock_complete_checkout.assert_not_called()
