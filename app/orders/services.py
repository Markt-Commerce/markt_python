# python imports
from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError

# project imports
from external.database import db
from app.libs.session import session_scope
from app.libs.errors import (
    NotFoundError,
    ValidationError,
    ConflictError,
    ForbiddenError,
    APIError,
)
from app.libs.pagination import Paginator

from app.cart.models import Cart, CartItem
from app.notifications.models import NotificationType
from app.notifications.services import NotificationService
from app.products.models import Product
from app.payments.models import Payment, PaymentStatus
from app.users.models import Buyer
from app.products.services import ProductService

# app imports
from .models import (
    Order,
    OrderStatus,
    OrderItem,
    FulfilmentPreference,
    ShippingAddress,
    Shipment,
    OrderReturn,
    OrderReturnStatus,
)
from app.orders.shipping import (
    normalize_shipping_address,
    shipping_address_to_model_kwargs,
)
from app.orders.events import ActorType, OrderEventService, OrderEventType

logger = logging.getLogger(__name__)

BUYER_CANCELLABLE_STATUSES = {
    OrderStatus.PENDING_PAYMENT,
    OrderStatus.PENDING,
    OrderStatus.PROCESSING,
    OrderStatus.READY_FOR_DELIVERY,
}

RETURNABLE_ORDER_STATUSES = {
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
}


class OrderService:
    @staticmethod
    def create_order(cart_id, buyer_id, shipping_address, payment_method):
        try:
            with session_scope() as session:
                cart = (
                    session.query(Cart)
                    .options(db.joinedload(Cart.items).joinedload(CartItem.product))
                    .get(cart_id)
                )

                if not cart:
                    raise NotFoundError("Cart not found")
                if cart.buyer_id != buyer_id:
                    raise ForbiddenError("Cart does not belong to user")
                if not cart.items:
                    raise ValidationError("Cannot create order from empty cart")

                # Validate shipping address
                shipping_normalized = normalize_shipping_address(shipping_address)

                # Create single order for buyer
                # Note: This method is deprecated in favor of CartService.checkout_cart()
                # Keeping for backward compatibility but should use checkout_cart for full totals
                order = Order(
                    buyer_id=buyer_id,
                    subtotal=cart.subtotal(),
                    status=OrderStatus.PENDING_PAYMENT,  # Use explicit status
                    # TODO: Calculate shipping_fee, tax, discount, total here
                    # For now, these will be null and should be calculated
                )
                session.add(order)
                session.flush()

                # Create shipping address
                shipping_address_obj = ShippingAddress(
                    order_id=order.id,
                    **shipping_address_to_model_kwargs(shipping_normalized),
                )
                session.add(shipping_address_obj)

                # Create order items for each product
                for item in cart.items:
                    order_item = OrderItem(
                        order_id=order.id,
                        product_id=item.product_id,
                        variant_id=item.variant_id,
                        seller_id=item.product.seller_id,  # Critical - track seller
                        quantity=item.quantity,
                        price=item.product_price,
                        status=OrderItem.Status.PENDING,
                    )
                    session.add(order_item)
                    # Explicitly add to order's items collection
                    order.items.append(order_item)

                # Commit changes to ensure items are persisted
                session.commit()

                order.order_number = order.generate_order_number()
                cart.clear_cart()
                return order
        except SQLAlchemyError as e:
            logger.error(f"Database error creating order: {str(e)}")
            raise APIError("Failed to create order", 500)

    @staticmethod
    def create_order_from_checkout_snapshot(
        session, snapshot: Dict[str, Any], buyer_id: int
    ) -> Order:
        """Build the Order + OrderItems from a payment-first checkout
        snapshot, called from within the same transaction that just marked
        the payment COMPLETED (see PaymentService.complete_checkout_payment).
        Payment is already captured by the time this runs -- unlike
        create_order/checkout_cart's PENDING_PAYMENT start, the order and
        its items start straight at the "paid" state."""
        order = Order(
            buyer_id=buyer_id,
            status=OrderStatus.READY_FOR_DELIVERY,
            subtotal=snapshot["subtotal"],
            shipping_fee=snapshot["shipping_fee"],
            service_fee=snapshot.get("service_fee"),
            reliability_fee_opted_in=snapshot.get("reliability_fee_opted_in", False),
            reliability_fee_estimate=snapshot.get("reliability_fee_estimate"),
            total=snapshot["total"],
        )
        session.add(order)
        session.flush()

        shipping_address_obj = ShippingAddress(
            order_id=order.id,
            **shipping_address_to_model_kwargs(snapshot["shipping_address"]),
        )
        session.add(shipping_address_obj)

        # 10.1: best-effort Area resolution for DeliveryRun eligibility --
        # see MarketService.resolve_area_for_coordinates and
        # ShippingAddress.area_id's own docstring for why this is
        # best-effort rather than required.
        from app.markets.services import MarketService

        area = MarketService.resolve_area_for_coordinates(
            session,
            shipping_address_obj.latitude,
            shipping_address_obj.longitude,
        )
        if area:
            shipping_address_obj.area_id = area.id

        # 6: one preference per order, set at checkout, stamped onto every
        # item -- see FulfilmentPreference's docstring for why it's stored
        # per-item rather than requiring a join back to Order later. Falls
        # back to AUTO for a missing/unrecognised value rather than
        # rejecting the whole checkout over it.
        try:
            fulfilment_preference = FulfilmentPreference(
                snapshot.get("fulfilment_preference", FulfilmentPreference.AUTO.value)
            )
        except ValueError:
            fulfilment_preference = FulfilmentPreference.AUTO

        for item in snapshot["items"]:
            order_item = OrderItem(
                order_id=order.id,
                product_id=item["product_id"],
                variant_id=item.get("variant_id"),
                seller_id=item["seller_id"],
                quantity=item["quantity"],
                price=item["price"],
                status=OrderItem.Status.PROCESSING,
                fulfilment_preference=fulfilment_preference,
            )
            session.add(order_item)
            order.items.append(order_item)

        session.flush()
        order.order_number = order.generate_order_number()
        session.flush()

        OrderEventService.emit(
            session,
            order_id=order.id,
            event_type=OrderEventType.ORDER_CREATED,
            actor_type=ActorType.BUYER,
            actor_id=str(buyer_id),
            metadata={"item_count": len(snapshot["items"]), "total": order.total},
        )

        return order

    @staticmethod
    def _get_geocoordinates(address_dict):
        """Backward-compatible wrapper around shared geocoding helper."""
        from app.orders.shipping import geocode_address

        return geocode_address(address_dict)

    @staticmethod
    def get_user_orders(user_id):
        """For buyers - shows complete orders with all items"""
        with session_scope() as session:
            return (
                session.query(Order)
                .options(
                    db.joinedload(Order.items).joinedload(OrderItem.product),
                    db.joinedload(Order.items).joinedload(OrderItem.seller),
                )
                .filter_by(buyer_id=user_id)
                .order_by(Order.created_at.desc())
                .all()
            )

    @staticmethod
    def get_order(order_id):
        with session_scope() as session:
            return (
                session.query(Order)
                .options(
                    db.joinedload(Order.items).joinedload(OrderItem.product),
                    db.joinedload(Order.items).joinedload(OrderItem.seller),
                    db.joinedload(Order.items).joinedload(OrderItem.variant),
                    db.joinedload(Order.payments),
                )
                .get(order_id)
            )

    @staticmethod
    def get_order_events(order_id: str, buyer_id: int) -> List["OrderEvent"]:
        """14.2/15: buyer-facing fulfilment history for one order --
        "the buyer can inspect fulfilment history (who fulfilled, why a
        substitution happened), sourced from the event log." Deliberately
        NOT filtered down to a "customer-friendly" subset -- 15's
        notify/don't-notify distinction is about proactive notifications,
        not what's inspectable on request; the full chronological history
        (including a first seller's decline before a reroute succeeded)
        is exactly the transparency this is for."""
        from .events import OrderEvent

        with session_scope() as session:
            order = session.query(Order).filter_by(id=order_id).first()
            if not order:
                raise NotFoundError("Order not found")
            if order.buyer_id != buyer_id:
                raise ForbiddenError("You can only view your own order's history")

            return (
                session.query(OrderEvent)
                .filter_by(order_id=order_id)
                .order_by(OrderEvent.created_at.asc())
                .all()
            )

    @staticmethod
    def process_payment(order_id, payment_data):
        """
        DEPRECATED: This method is deprecated. Use PaymentService.create_payment() instead.

        This method was a mock implementation. For real payment processing,
        use PaymentService.create_payment() and PaymentService.process_payment().

        Kept for backward compatibility but will redirect to PaymentService.
        """
        from app.payments.services import PaymentService

        # Get order to determine amount
        order = OrderService.get_order(order_id)
        if not order:
            raise NotFoundError("Order not found")

        # Use PaymentService instead
        payment = PaymentService.create_payment(
            order_id=order_id,
            amount=order.total
            or order.subtotal,  # Fallback to subtotal if total not set
            currency="NGN",
            method=payment_data.get("method", "card"),
            metadata=payment_data.get("metadata"),
        )

        # If payment_data has processing info, process it
        if payment_data.get("authorization_code") or payment_data.get("bank"):
            payment = PaymentService.process_payment(payment.id, payment_data)

        return payment

    @staticmethod
    def update_order_status(order_id, new_status):
        with session_scope() as session:
            order = session.query(Order).get(order_id)
            if not order:
                raise NotFoundError("Order not found")

            old_status = order.status
            order.status = new_status

            # Queue async real-time event (non-blocking)
            try:
                from app.realtime.event_manager import EventManager

                EventManager.emit_to_order(
                    order_id,
                    "order_status_changed",
                    {
                        "order_id": order_id,
                        "user_id": order.buyer.user_id if order.buyer else None,
                        "status": new_status.value,
                        "old_status": old_status.value if old_status else None,
                        "metadata": {
                            "order_number": order.order_number,
                            "total": order.total,
                        },
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to queue order_status_changed event: {e}")

        # Post-commit: gamification points (award on delivery, reverse on
        # cancel/return of a previously-delivered order).
        if new_status == OrderStatus.DELIVERED and old_status != OrderStatus.DELIVERED:
            OrderService._emit_gam_order_completed(order_id)
        elif (
            new_status
            in (OrderStatus.CANCELLED, OrderStatus.RETURNED, OrderStatus.FAILED)
            and old_status == OrderStatus.DELIVERED
        ):
            OrderService._emit_gam_order_reversed(order_id)

        return order

    @staticmethod
    def _emit_gam_order_completed(order_id):
        try:
            from app.signals import order_completed

            order_completed.send("orders", order_id=order_id)
        except Exception as e:  # never let gamification break order flow
            logger.warning(f"gamification order_completed emit failed: {e}")

    @staticmethod
    def _emit_gam_order_reversed(order_id):
        try:
            from app.signals import order_reversed

            order_reversed.send("orders", order_id=order_id)
        except Exception as e:
            logger.warning(f"gamification order_reversed emit failed: {e}")

    @staticmethod
    def _get_completed_payment_amount(order: Order) -> float:
        """The amount actually captured for this order. Includes
        PARTIALLY_REFUNDED, not just COMPLETED -- Payment.amount is never
        mutated by a refund (only Payment.status changes; see
        refund_unresolved_item), so a payment that's already had one
        partial refund applied still represents the same captured amount
        it always did. Without this, a second refund against the same
        order (whole-order cancel after a per-item refund, or two
        per-item refunds) would see captured=0 and skip the invariant
        entirely."""
        for payment in order.payments or []:
            if payment.status in (
                PaymentStatus.COMPLETED,
                PaymentStatus.PARTIALLY_REFUNDED,
            ):
                return payment.amount
        return 0.0

    @staticmethod
    def _get_total_refunded(session, order: Order) -> float:
        """Sum of every wallet refund already issued against this order or
        any of its items (see refund_unresolved_item) -- needed so the
        invariant below is cumulative, not just "does this one refund fit,"
        now that an order can be refunded more than once (whole-order
        cancel/return, plus per-item ASK-timeout refunds)."""
        from app.wallet.models import WalletEntry, WalletEntryType, WalletReferenceType

        reference_ids = [order.id] + [item.id for item in order.items or []]
        reference_ids = [str(ref_id) for ref_id in reference_ids]
        total = (
            session.query(db.func.coalesce(db.func.sum(WalletEntry.amount), 0.0))
            .filter(
                WalletEntry.reference_type == WalletReferenceType.ORDER_REFUND,
                WalletEntry.reference_id.in_(reference_ids),
                WalletEntry.entry_type == WalletEntryType.CREDIT,
            )
            .scalar()
        )
        return float(total or 0.0)

    @staticmethod
    def _assert_refund_within_captured(
        order: Order, refund_amount: float, session=None
    ) -> None:
        """Escrow invariant: cumulative refunds can never exceed what was
        actually captured. `session` is optional (existing callers that
        only ever refund an order once didn't need it) -- pass it whenever
        the order could plausibly already have a prior refund against it,
        so already-refunded amounts are accounted for rather than silently
        allowed to stack past the captured total."""
        captured = OrderService._get_completed_payment_amount(order)
        if not captured:
            return
        already_refunded = (
            OrderService._get_total_refunded(session, order) if session else 0.0
        )
        if already_refunded + refund_amount > captured + 0.01:
            raise ValidationError(
                f"Refund amount {refund_amount} (already refunded "
                f"{already_refunded}) exceeds captured payment amount "
                f"{captured} for order {order.id}"
            )

    @staticmethod
    def cancel_order(order_id: str, buyer_id: int, reason: Optional[str] = None):
        """Cancel an order on behalf of the buyer."""
        from app.wallet.services import WalletService

        paid_amount = 0.0
        buyer_user_id = None
        order_items = []

        with session_scope() as session:
            order = (
                session.query(Order)
                .options(
                    db.joinedload(Order.items),
                    db.joinedload(Order.payments),
                    db.joinedload(Order.buyer),
                )
                .get(order_id)
            )

            if not order:
                raise NotFoundError("Order not found")
            if order.buyer_id != buyer_id:
                raise ForbiddenError("You can only cancel your own orders")
            if order.status == OrderStatus.CANCELLED:
                raise ConflictError("Order is already cancelled")
            if order.status not in BUYER_CANCELLABLE_STATUSES:
                raise ValidationError(
                    f"Order in status '{order.status.value}' cannot be cancelled"
                )

            captured_amount = OrderService._get_completed_payment_amount(order)
            # Only refund what hasn't already gone out -- an item may have
            # been refunded on its own earlier (see refund_unresolved_item,
            # 11.8/9.1) before the buyer cancels the rest of the order.
            already_refunded = OrderService._get_total_refunded(session, order)
            paid_amount = round(max(captured_amount - already_refunded, 0.0), 2)
            buyer_user_id = order.buyer.user_id if order.buyer else None
            order_items = list(order.items)

            order.status = OrderStatus.CANCELLED
            order.cancelled_at = datetime.utcnow()
            order.cancel_reason = reason

            for item in order.items:
                if item.status != OrderItem.Status.CANCELLED:
                    item.status = OrderItem.Status.CANCELLED

            if paid_amount > 0:
                OrderService._assert_refund_within_captured(
                    order, paid_amount, session=session
                )
            for payment in order.payments:
                if payment.status in (
                    PaymentStatus.COMPLETED,
                    PaymentStatus.PARTIALLY_REFUNDED,
                ):
                    payment.transition_to(PaymentStatus.REFUNDED)

            OrderEventService.emit(
                session,
                order_id=order_id,
                event_type=OrderEventType.ORDER_CANCELLED,
                actor_type=ActorType.BUYER,
                actor_id=str(buyer_id),
                metadata={"reason": reason, "refund_amount": paid_amount},
            )

            session.flush()

        if paid_amount > 0:
            ProductService.restore_inventory_for_order(order_items)
            if buyer_user_id:
                WalletService.refund_order_to_wallet(
                    buyer_user_id, order_id, paid_amount
                )

        if buyer_user_id:
            try:
                NotificationService.create_notification(
                    user_id=buyer_user_id,
                    notification_type=NotificationType.ORDER_CANCELLED,
                    reference_type="order",
                    reference_id=order_id,
                    metadata_={"order_id": order_id},
                )
                if paid_amount > 0:
                    NotificationService.create_notification(
                        user_id=buyer_user_id,
                        notification_type=NotificationType.REFUND_ISSUED,
                        reference_type="order",
                        reference_id=order_id,
                        metadata_={
                            "message": (
                                f"₦{paid_amount:.2f} was refunded to your "
                                "wallet for a cancelled order."
                            )
                        },
                    )
            except Exception:
                logger.exception(
                    "Failed to notify buyer of order %s cancellation/refund",
                    order_id,
                )

        try:
            from app.realtime.event_manager import EventManager

            EventManager.emit_to_order(
                order_id,
                "order_status_changed",
                {
                    "order_id": order_id,
                    "user_id": buyer_user_id,
                    "status": OrderStatus.CANCELLED.value,
                    "metadata": {"cancel_reason": reason},
                },
            )
        except Exception as e:
            logger.warning(f"Failed to queue order_status_changed event: {e}")

        return OrderService.get_order(order_id)

    @staticmethod
    def track_order(order_id: str, user_id: str) -> Dict[str, Any]:
        """Return order tracking timeline for buyer or participating seller."""
        from app.deliveries.models import DeliveryOrderAssignment, AssignmentStatus

        with session_scope() as session:
            order = (
                session.query(Order)
                .options(
                    db.joinedload(Order.items).joinedload(OrderItem.seller),
                    db.joinedload(Order.shipping_address),
                    db.joinedload(Order.shipments),
                    db.joinedload(Order.payments),
                    db.joinedload(Order.buyer),
                )
                .get(order_id)
            )

            if not order:
                raise NotFoundError("Order not found")

            is_buyer = order.buyer and order.buyer.user_id == user_id
            is_seller = any(
                item.seller and item.seller.user_id == user_id for item in order.items
            )
            if not is_buyer and not is_seller:
                raise ForbiddenError("You do not have access to track this order")

            assignment = (
                session.query(DeliveryOrderAssignment)
                .filter_by(order_id=order_id)
                .order_by(DeliveryOrderAssignment.assigned_at.desc())
                .first()
            )

            latest_payment = None
            for payment in sorted(
                order.payments or [], key=lambda p: p.created_at or datetime.min
            ):
                if payment.status == PaymentStatus.COMPLETED:
                    latest_payment = payment

            timeline = [
                {
                    "status": "created",
                    "label": "Order placed",
                    "timestamp": (
                        order.created_at.isoformat() if order.created_at else None
                    ),
                }
            ]
            if latest_payment and latest_payment.paid_at:
                timeline.append(
                    {
                        "status": "paid",
                        "label": "Payment confirmed",
                        "timestamp": latest_payment.paid_at.isoformat(),
                    }
                )
            if order.cancelled_at:
                timeline.append(
                    {
                        "status": "cancelled",
                        "label": "Order cancelled",
                        "timestamp": order.cancelled_at.isoformat(),
                    }
                )
            elif order.status == OrderStatus.DELIVERED:
                timeline.append(
                    {
                        "status": "delivered",
                        "label": "Delivered",
                        "timestamp": (
                            order.updated_at.isoformat() if order.updated_at else None
                        ),
                    }
                )

            shipment = order.shipments[0] if order.shipments else None
            delivery_info = None
            if assignment and assignment.status == AssignmentStatus.ACCEPTED:
                delivery_info = {
                    "assignment_id": assignment.assignment_id,
                    "status": assignment.status.value,
                    "logistical_status": (
                        assignment.logistical_status.value
                        if assignment.logistical_status
                        else None
                    ),
                    "assigned_at": (
                        assignment.assigned_at.isoformat()
                        if assignment.assigned_at
                        else None
                    ),
                }

            return {
                "order_id": order.id,
                "order_number": order.order_number,
                "status": order.status.value,
                "timeline": timeline,
                "shipping_address": order.shipping_address_dict,
                "items": [
                    {
                        "id": item.id,
                        "product_id": item.product_id,
                        "quantity": item.quantity,
                        "status": item.status.value,
                        "seller_id": item.seller_id,
                    }
                    for item in order.items
                ],
                "shipment": (
                    {
                        "carrier": shipment.carrier,
                        "tracking_number": shipment.tracking_number,
                        "tracking_url": shipment.tracking_url,
                        "status": shipment.status,
                        "shipped_at": (
                            shipment.shipped_at.isoformat()
                            if shipment and shipment.shipped_at
                            else None
                        ),
                        "delivered_at": (
                            shipment.delivered_at.isoformat()
                            if shipment and shipment.delivered_at
                            else None
                        ),
                    }
                    if shipment
                    else None
                ),
                "delivery": delivery_info,
            }

    @staticmethod
    def request_return(order_id: str, buyer_id: int, reason: str) -> OrderReturn:
        """Buyer requests a return for a shipped or delivered order."""
        if not reason or not reason.strip():
            raise ValidationError("Return reason is required")

        with session_scope() as session:
            order = (
                session.query(Order).options(db.joinedload(Order.items)).get(order_id)
            )
            if not order:
                raise NotFoundError("Order not found")
            if order.buyer_id != buyer_id:
                raise ForbiddenError("You can only request returns for your own orders")
            if order.status not in RETURNABLE_ORDER_STATUSES:
                raise ValidationError(
                    f"Returns are not available for orders in '{order.status.value}' status"
                )

            existing = (
                session.query(OrderReturn)
                .filter(
                    OrderReturn.order_id == order_id,
                    OrderReturn.status.in_(
                        [OrderReturnStatus.REQUESTED, OrderReturnStatus.APPROVED]
                    ),
                )
                .first()
            )
            if existing:
                raise ConflictError("A return request is already open for this order")

            paid_amount = OrderService._get_completed_payment_amount(order)
            order_return = OrderReturn(
                order_id=order_id,
                buyer_id=buyer_id,
                reason=reason.strip(),
                status=OrderReturnStatus.REQUESTED,
                refund_amount=paid_amount if paid_amount > 0 else order.total,
            )
            session.add(order_return)
            session.flush()
            return order_return

    @staticmethod
    def approve_return(
        return_id: str, seller_id: int, seller_notes: Optional[str] = None
    ):
        """Seller approves a return and refunds the buyer to wallet."""
        from app.wallet.services import WalletService

        refund_amount = 0.0
        buyer_user_id = None
        order_id = None

        with session_scope() as session:
            order_return = (
                session.query(OrderReturn)
                .options(
                    db.joinedload(OrderReturn.order).joinedload(Order.items),
                    db.joinedload(OrderReturn.order).joinedload(Order.buyer),
                    db.joinedload(OrderReturn.order).joinedload(Order.payments),
                )
                .get(return_id)
            )
            if not order_return:
                raise NotFoundError("Return request not found")
            if order_return.status != OrderReturnStatus.REQUESTED:
                raise ConflictError("Return request is not pending approval")

            order = order_return.order
            is_seller = any(item.seller_id == seller_id for item in order.items)
            if not is_seller:
                raise ForbiddenError("Only a seller on this order can approve returns")

            refund_amount = (
                order_return.refund_amount
                or OrderService._get_completed_payment_amount(order)
            )
            if refund_amount <= 0:
                refund_amount = order.total or 0.0

            OrderService._assert_refund_within_captured(
                order, refund_amount, session=session
            )

            buyer_user_id = order.buyer.user_id if order.buyer else None
            order_id = order.id

            order_return.status = OrderReturnStatus.REFUNDED
            order_return.seller_notes = seller_notes
            order.status = OrderStatus.RETURNED

            for item in order.items:
                if item.status != OrderItem.Status.CANCELLED:
                    item.status = OrderItem.Status.CANCELLED

            for payment in order.payments or []:
                if payment.status in (
                    PaymentStatus.COMPLETED,
                    PaymentStatus.PARTIALLY_REFUNDED,
                ):
                    payment.transition_to(PaymentStatus.REFUNDED)

            session.flush()

        if refund_amount > 0 and buyer_user_id:
            from app.wallet.models import WalletReferenceType

            WalletService.credit(
                buyer_user_id,
                refund_amount,
                WalletReferenceType.ORDER_REFUND,
                return_id,
                description=f"Return refund for order {order_id}",
                idempotency_key=f"return-refund:{return_id}",
            )
            try:
                NotificationService.create_notification(
                    user_id=buyer_user_id,
                    notification_type=NotificationType.REFUND_ISSUED,
                    reference_type="order",
                    reference_id=order_id,
                    metadata_={
                        "message": (
                            f"₦{refund_amount:.2f} was refunded to your "
                            "wallet for your approved return."
                        )
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to notify buyer of return refund for order %s", order_id
                )

        # Post-commit: claw back any gamification points earned on this order.
        if order_id:
            OrderService._emit_gam_order_reversed(order_id)

        return order_return

    @staticmethod
    def refund_unresolved_item(
        order_item_id: int, reason: Optional[str] = None
    ) -> Optional["WalletEntry"]:
        """11.8 / 9.1: refund a single item that couldn't be fulfilled,
        without touching the rest of the order -- distinct from
        cancel_order (whole order, buyer-initiated) and approve_return
        (whole order, post-delivery). Today's only caller is the ASK
        timeout worker (app.fulfilment.tasks.expire_stale_buyer_approvals,
        9.1's "remove the unresolved item and adjust/refund" MVP policy),
        but this is a standalone reusable primitive -- flagged as needed
        back in Phase 4, genuinely blocked until an item-level "couldn't
        be fulfilled" outcome existed to call it from.

        Idempotent: a no-op (returns None) if the item is already
        CANCELLED -- safe to call more than once for the same item.

        Simplification, flagged: always marks the order's payment(s)
        PARTIALLY_REFUNDED, even in the edge case where this happens to be
        the order's only remaining un-refunded item (which would really be
        a full refund). Detecting that would mean summing every other
        item's own state here; not worth it for a label that doesn't
        change the actual money movement -- cancel_order still correctly
        finishes the job (-> REFUNDED) if the buyer goes on to cancel the
        rest of the order.
        """
        from app.wallet.services import WalletService

        refund_amount = 0.0
        buyer_user_id = None

        with session_scope() as session:
            order_item = (
                session.query(OrderItem)
                .options(
                    db.joinedload(OrderItem.order).joinedload(Order.payments),
                    db.joinedload(OrderItem.order).joinedload(Order.buyer),
                    db.joinedload(OrderItem.order).joinedload(Order.items),
                )
                .get(order_item_id)
            )
            if not order_item:
                raise NotFoundError("Order item not found")

            if order_item.status == OrderItem.Status.CANCELLED:
                return None

            order = order_item.order
            refund_amount = round(
                (order_item.price or 0) * (order_item.quantity or 0), 2
            )

            if refund_amount > 0:
                OrderService._assert_refund_within_captured(
                    order, refund_amount, session=session
                )

            order_item.transition_to(OrderItem.Status.CANCELLED)

            for payment in order.payments or []:
                if payment.status in (
                    PaymentStatus.COMPLETED,
                    PaymentStatus.PARTIALLY_REFUNDED,
                ):
                    payment.transition_to(PaymentStatus.PARTIALLY_REFUNDED)

            buyer_user_id = order.buyer.user_id if order.buyer else None

            OrderEventService.emit(
                session,
                order_id=order.id,
                order_item_id=order_item_id,
                event_type=OrderEventType.ITEM_REFUNDED,
                actor_type=ActorType.SYSTEM,
                metadata={"reason": reason, "refund_amount": refund_amount},
                idempotency_key=f"event:item_refunded:{order_item_id}",
            )

            session.flush()

        if refund_amount > 0 and buyer_user_id:
            entry = WalletService.refund_order_item_to_wallet(
                buyer_user_id, order_item_id, refund_amount, reason=reason
            )
            try:
                NotificationService.create_notification(
                    user_id=buyer_user_id,
                    notification_type=NotificationType.REFUND_ISSUED,
                    reference_type="order_item",
                    reference_id=str(order_item_id),
                    metadata_={
                        "message": (
                            f"₦{refund_amount:.2f} was refunded to your "
                            "wallet for an item that couldn't be fulfilled."
                        )
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to notify buyer of item %s refund", order_item_id
                )
            return entry
        return None

    @staticmethod
    def reject_return(
        return_id: str, seller_id: int, seller_notes: Optional[str] = None
    ):
        """Seller rejects a return request."""
        with session_scope() as session:
            order_return = (
                session.query(OrderReturn)
                .options(db.joinedload(OrderReturn.order).joinedload(Order.items))
                .get(return_id)
            )
            if not order_return:
                raise NotFoundError("Return request not found")
            if order_return.status != OrderReturnStatus.REQUESTED:
                raise ConflictError("Return request is not pending approval")

            is_seller = any(
                item.seller_id == seller_id for item in order_return.order.items
            )
            if not is_seller:
                raise ForbiddenError("Only a seller on this order can reject returns")

            order_return.status = OrderReturnStatus.REJECTED
            order_return.seller_notes = seller_notes
            session.flush()
            return order_return

    # TODO: Add order history tracking
    # TODO: Add refund processing


class SellerOrderService:
    @staticmethod
    def get_seller_orders(seller_id, status=None, page=1, per_page=20):
        """For sellers - shows only their order items"""
        with session_scope() as session:
            base_query = (
                session.query(OrderItem)
                .filter_by(seller_id=seller_id)
                .options(
                    db.joinedload(OrderItem.order).joinedload(Order.buyer),
                    db.joinedload(OrderItem.product),
                    db.joinedload(OrderItem.variant),
                )
            )

            if status:
                base_query = base_query.filter_by(status=status)

            paginator = Paginator(base_query, page=page, per_page=per_page)
            result = paginator.paginate({})

            return {
                "items": result["items"],
                "pagination": {
                    "page": result["page"],
                    "per_page": result["per_page"],
                    "total_items": result["total_items"],
                    "total_pages": result["total_pages"],
                },
            }

    @staticmethod
    def update_order_item_status(order_item_id, status, seller_id):
        order_id = None
        all_delivered = False

        with session_scope() as session:
            item = (
                session.query(OrderItem)
                .options(db.joinedload(OrderItem.seller))
                .filter_by(id=order_item_id, seller_id=seller_id)
                .first()
            )

            if not item:
                raise ValueError("Order item not found")

            item.transition_to(status)
            order_id = item.order_id

            if status == OrderItem.Status.DELIVERED:
                order = session.query(Order).get(order_id)
                all_delivered = all(
                    i.status == OrderItem.Status.DELIVERED for i in order.items
                )

                # Starts the settlement hold (Phase 0: 12h) rather than
                # paying out immediately -- see
                # WalletService.settle_eligible_order_items.
                if item.delivered_at is None:
                    item.delivered_at = datetime.utcnow()

        # Post-commit: delegate order-level completion (status, realtime
        # event, gamification) to the single source of truth once every item
        # on the order is in, instead of setting order.status here too.
        if status == OrderItem.Status.DELIVERED and all_delivered:
            OrderService.update_order_status(order_id, OrderStatus.DELIVERED)

        return item

    @staticmethod
    def get_seller_order_stats(seller_id):
        with session_scope() as session:
            return {
                "total_orders": session.query(OrderItem)
                .filter_by(seller_id=seller_id)
                .count(),
                "pending_orders": session.query(OrderItem)
                .filter_by(seller_id=seller_id, status=OrderItem.Status.PENDING)
                .count(),
                "monthly_earnings": session.query(
                    db.func.sum(OrderItem.price * OrderItem.quantity)
                )
                .filter(
                    OrderItem.seller_id == seller_id,
                    OrderItem.created_at >= (datetime.utcnow() - timedelta(days=30)),
                )
                .scalar()
                or 0,
            }
