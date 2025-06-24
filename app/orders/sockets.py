import logging
from datetime import datetime
from flask_socketio import Namespace, emit, join_room, leave_room
from flask_login import current_user
from external.redis import redis_client

logger = logging.getLogger(__name__)


class OrderNamespace(Namespace):
    def on_connect(self):
        """Handle client connection for order features"""
        if not current_user.is_authenticated:
            logger.warning("Unauthorized order connection attempt")
            return emit("error", {"message": "Unauthorized"})

        # Join user-specific room
        join_room(f"user_{current_user.id}")

        # Join role-specific rooms
        if current_user.is_buyer:
            join_room(f"buyer_{current_user.buyer_account.id}")
        if current_user.is_seller:
            join_room(f"seller_{current_user.seller_account.id}")

        # Mark user as online for orders
        redis_client.set(f"user_online_orders:{current_user.id}", "1", ex=300)
        emit("connected", {"status": "connected"})
        logger.info(f"User {current_user.id} connected to orders")

    def on_disconnect(self):
        """Handle client disconnection"""
        if current_user.is_authenticated:
            leave_room(f"user_{current_user.id}")
            if current_user.is_buyer:
                leave_room(f"buyer_{current_user.buyer_account.id}")
            if current_user.is_seller:
                leave_room(f"seller_{current_user.seller_account.id}")

            redis_client.delete(f"user_online_orders:{current_user.id}")
            logger.info(f"User {current_user.id} disconnected from orders")

    # ==================== ORDER TRACKING ====================
    def on_join_order(self, order_id):
        """Join room for specific order updates"""
        if current_user.is_authenticated:
            join_room(f"order_{order_id}")

            # Get current order status
            from app.orders.services import OrderService

            try:
                order = OrderService.get_order(order_id)
                emit(
                    "order_status",
                    {
                        "order_id": order_id,
                        "status": order.status.value,
                        "last_updated": order.updated_at.isoformat(),
                    },
                )
            except Exception as e:
                logger.error(f"Error getting order status: {str(e)}")
                emit("error", {"message": "Failed to get order status"})

    def on_leave_order(self, order_id):
        """Leave order room"""
        if current_user.is_authenticated:
            leave_room(f"order_{order_id}")

    # ==================== PAYMENT UPDATES ====================
    def on_payment_status(self, payment_id):
        """Get payment status update"""
        if current_user.is_authenticated:
            from app.payments.services import PaymentService

            try:
                payment = PaymentService.get_payment(payment_id)
                emit(
                    "payment_update",
                    {
                        "payment_id": payment_id,
                        "status": payment.status.value,
                        "amount": payment.amount,
                        "updated_at": payment.updated_at.isoformat(),
                    },
                )
            except Exception as e:
                logger.error(f"Error getting payment status: {str(e)}")
                emit("error", {"message": "Failed to get payment status"})

    # ==================== SELLER ORDER MANAGEMENT ====================
    def on_join_seller_orders(self):
        """Join room for seller order updates"""
        if current_user.is_authenticated and current_user.is_seller:
            join_room(f"seller_orders_{current_user.seller_account.id}")

            # Get pending orders count
            from app.orders.services import SellerOrderService

            try:
                stats = SellerOrderService.get_seller_order_stats(
                    current_user.seller_account.id
                )
                emit(
                    "seller_stats",
                    {
                        "pending_orders": stats.get("pending_count", 0),
                        "total_orders": stats.get("total_count", 0),
                        "revenue": stats.get("total_revenue", 0),
                    },
                )
            except Exception as e:
                logger.error(f"Error getting seller stats: {str(e)}")

    def on_leave_seller_orders(self):
        """Leave seller orders room"""
        if current_user.is_authenticated and current_user.is_seller:
            leave_room(f"seller_orders_{current_user.seller_account.id}")

    # ==================== UTILITY ====================
    def on_ping(self, data):
        """Keep connection alive"""
        if current_user.is_authenticated:
            redis_client.set(f"user_online_orders:{current_user.id}", "1", ex=300)
            emit("pong", {"timestamp": datetime.utcnow().isoformat()})
