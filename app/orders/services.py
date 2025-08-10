# python imports
from datetime import datetime
import logging

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
from app.products.models import Product
from app.payments.models import Payment, PaymentStatus
from app.users.models import Buyer

# app imports
from .models import Order, OrderStatus, OrderItem


logger = logging.getLogger(__name__)


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

                # Create single order for buyer
                order = Order(
                    buyer_id=buyer_id,
                    shipping_address=shipping_address,
                    subtotal=cart.subtotal(),
                    status=OrderStatus.PENDING,
                )
                session.add(order)
                session.flush()

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
    def process_payment(order_id, payment_data):
        with session_scope() as session:
            order = session.query(Order).get(order_id)
            if not order:
                raise ValueError("Order not found")

            # Mock payment processing
            payment = Payment(
                order_id=order_id,
                amount=order.total,
                method=payment_data["method"],
                status=PaymentStatus.COMPLETED,
                transaction_id=f"mock_{datetime.now().timestamp()}",
                paid_at=datetime.utcnow(),
            )
            session.add(payment)

            # Update order status
            order.status = OrderStatus.PROCESSING

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

            return order

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
        with session_scope() as session:
            item = (
                session.query(OrderItem)
                .filter_by(id=order_item_id, seller_id=seller_id)
                .first()
            )

            if not item:
                raise ValueError("Order item not found")

            valid_transitions = {
                OrderItem.Status.PENDING: [
                    OrderItem.Status.PROCESSING,
                    OrderItem.Status.CANCELLED,
                ],
                OrderItem.Status.PROCESSING: [
                    OrderItem.Status.SHIPPED,
                    OrderItem.Status.CANCELLED,
                ],
                OrderItem.Status.SHIPPED: [OrderItem.Status.DELIVERED],
                # Other status transitions...
            }

            if (
                item.status not in valid_transitions
                or status not in valid_transitions[item.status]
            ):
                raise ValueError(f"Cannot transition from {item.status} to {status}")

            item.status = status

            # If all items are delivered, mark order as completed
            if status == OrderItem.Status.DELIVERED:
                order = session.query(Order).get(item.order_id)
                if all(i.status == OrderItem.Status.DELIVERED for i in order.items):
                    order.status = OrderStatus.DELIVERED

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
                    OrderItem.created_at
                    >= db.func.date_sub(db.func.now(), db.text("INTERVAL 1 MONTH")),
                )
                .scalar()
                or 0,
            }
