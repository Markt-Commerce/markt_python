# project imports
from app.libs.session import session_scope
from app.libs.errors import NotFoundError

# app imports
from .models import Order, OrderStatus


class OrderService:
    @staticmethod
    def create_order(order_data):
        with session_scope() as session:
            order = Order(**order_data)
            session.add(order)
            return order

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
