# python imports
from datetime import datetime, timedelta
import logging
import requests

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
from .models import Order, OrderStatus, OrderItem, ShippingAddress


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

                # Validate shipping address
                required_fields = ['recipient_name', 'street_address', 'city', 'state', 'postal_code', 'country']
                for field in required_fields:
                    if field not in shipping_address or not shipping_address[field]:
                        raise ValidationError(f"Missing required shipping address field: {field}")

                # Check for longitude and latitude
                if 'longitude' not in shipping_address or 'latitude' not in shipping_address:
                    lat, lon = OrderService._get_geocoordinates(shipping_address)
                    shipping_address['latitude'] = lat
                    shipping_address['longitude'] = lon

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
                shipping_address_obj = ShippingAddress(order_id=order.id, **shipping_address)
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
    def _get_geocoordinates(address_dict):
        """
        Get geocoordinates from address using Nominatim API.
        Returns (latitude, longitude) as floats.
        If fails, returns (0.0, 0.0)
        """
        try:
            # Construct address string
            address_parts = [
                address_dict.get('street_address', ''),
                address_dict.get('city', ''),
                address_dict.get('state', ''),
                address_dict.get('postal_code', ''),
                address_dict.get('country', '')
            ]
            address_str = ', '.join(part for part in address_parts if part)

            if not address_str:
                return 0.0, 0.0

            # Call Nominatim API
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                'q': address_str,
                'format': 'json',
                'limit': 1
            }
            headers = {
                'User-Agent': 'Markt-Commerce-OrderService/1.0'
            }

            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            if data:
                lat = float(data[0]['lat'])
                lon = float(data[0]['lon'])
                return lat, lon
            else:
                return 0.0, 0.0
        except Exception as e:
            logger.warning(f"Failed to get geocoordinates: {e}")
            return 0.0, 0.0

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
                    OrderItem.created_at >= (datetime.utcnow() - timedelta(days=30)),
                )
                .scalar()
                or 0,
            }
