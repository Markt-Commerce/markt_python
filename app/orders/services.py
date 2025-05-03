# python imports
from datetime import datetime
import logging

# project imports
from external.database import db
from app.libs.session import session_scope
from app.libs.errors import NotFoundError
from app.cart.models import Cart, CartItem
from app.products.models import Product
from app.payments.models import Payment, PaymentStatus

# app imports
from .models import Order, OrderStatus


logger = logging.getLogger(__name__)


class OrderService:
    @staticmethod
    def create_order(cart_id, buyer_id, shipping_address, payment_method):
        with session_scope() as session:
            # Get cart and validate
            cart = session.query(Cart).options(db.joinedload(Cart.items)).get(cart_id)

            if not cart or cart.buyer_id != buyer_id:
                raise ValueError("Invalid cart")

            if not cart.items:
                raise ValueError("Cart is empty")

            # Verify product availability
            for item in cart.items:
                product = session.query(Product).get(item.product_id)
                if not product or not product.is_available():
                    raise ValueError(f"Product {product.name} is not available")
                if item.variant_id:
                    # Check variant inventory here
                    pass

            # Create order
            order = Order(
                buyer_id=buyer_id,
                seller_id=...,  # Need logic for multi-seller orders
                shipping_address=shipping_address,
                items=[
                    {
                        "product_id": item.product_id,
                        "variant_id": item.variant_id,
                        "quantity": item.quantity,
                        "price": item.product_price,
                    }
                    for item in cart.items
                ],
                subtotal=cart.subtotal(),
                status=OrderStatus.PENDING,
            )
            session.add(order)
            session.flush()

            # Generate order number
            order.order_number = order.generate_order_number()

            # Clear cart
            session.query(CartItem).filter_by(cart_id=cart.id).delete()
            session.commit()

            return order

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
            order.status = new_status
            return order

    # TODO: Add order history tracking
    # TODO: Add refund processing
