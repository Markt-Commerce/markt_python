import logging
from datetime import datetime
from flask_socketio import Namespace, emit, join_room, leave_room
from flask_login import current_user
from external.redis import redis_client

logger = logging.getLogger(__name__)


class OrderNamespace(Namespace):
    """Enhanced order namespace with rate limiting and validation"""

    # Rate limiting configuration
    RATE_LIMITS = {
        "join_order": {"max_calls": 10, "window": 60},  # 10 joins per minute
        "payment_status": {"max_calls": 5, "window": 60},  # 5 status checks per minute
        "ping": {"max_calls": 30, "window": 60},  # 30 pings per minute
    }

    def _check_rate_limit(self, event_type: str, user_id: str) -> bool:
        """Check if user has exceeded rate limit for event type"""
        try:
            key = f"rate_limit:orders:{event_type}:{user_id}"
            current = redis_client.get(key)

            if current and int(current) >= self.RATE_LIMITS[event_type]["max_calls"]:
                return False

            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, self.RATE_LIMITS[event_type]["window"])
            pipe.execute()

            return True
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            return True  # Allow if rate limiting fails

    def _validate_data(self, data: dict, required_fields: list) -> tuple[bool, str]:
        """Validate incoming data"""
        if not data:
            return False, "No data provided"

        for field in required_fields:
            if field not in data:
                return False, f"Missing required field: {field}"

        return True, ""

    def on_connect(self):
        """Handle client connection for order features with enhanced error handling"""
        from main.sockets import SocketManager

        try:
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

            # Mark user as online using centralized manager
            SocketManager.mark_user_online(current_user.id, "orders")

            emit(
                "connected",
                {
                    "status": "connected",
                    "user_id": current_user.id,
                    "roles": {
                        "is_buyer": current_user.is_buyer,
                        "is_seller": current_user.is_seller,
                    },
                },
            )
            logger.info(f"User {current_user.id} connected to orders namespace")

        except Exception as e:
            logger.error(f"Order connection error: {e}")
            emit("error", {"message": "Connection failed"})

    def on_disconnect(self):
        """Handle client disconnection"""
        from main.sockets import SocketManager

        try:
            if current_user.is_authenticated:
                leave_room(f"user_{current_user.id}")
                if current_user.is_buyer:
                    leave_room(f"buyer_{current_user.buyer_account.id}")
                if current_user.is_seller:
                    leave_room(f"seller_{current_user.seller_account.id}")

                SocketManager.mark_user_offline(current_user.id)
                logger.info(
                    f"User {current_user.id} disconnected from orders namespace"
                )

        except Exception as e:
            logger.error(f"Order disconnection error: {e}")

    # ==================== ORDER TRACKING ====================
    def on_join_order(self, data):
        """Join room for specific order updates with validation"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("join_order", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["order_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            order_id = data.get("order_id")

            # Validate order exists and user has access
            from app.orders.services import OrderService

            if not OrderService.order_exists(order_id):
                return emit("error", {"message": "Order not found"})

            # Check if user has access to this order
            if not OrderService.user_has_access_to_order(current_user.id, order_id):
                return emit("error", {"message": "Access denied"})

            join_room(f"order_{order_id}")

            # Get current order status
            try:
                order = OrderService.get_order(order_id)
                emit(
                    "order_status",
                    {
                        "order_id": order_id,
                        "status": order.status.value,
                        "last_updated": order.updated_at.isoformat(),
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
            except Exception as e:
                logger.error(f"Error getting order status: {str(e)}")
                emit("error", {"message": "Failed to get order status"})

        except Exception as e:
            logger.error(f"Join order error: {e}")
            emit("error", {"message": "Failed to join order"})

    def on_leave_order(self, data):
        """Leave order room with validation"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["order_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            order_id = data.get("order_id")
            leave_room(f"order_{order_id}")

        except Exception as e:
            logger.error(f"Leave order error: {e}")
            emit("error", {"message": "Failed to leave order"})

    # ==================== PAYMENT UPDATES ====================
    def on_payment_status(self, data):
        """Get payment status update with validation"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("payment_status", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["payment_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            payment_id = data.get("payment_id")

            # Validate payment exists and user has access
            from app.payments.services import PaymentService

            if not PaymentService.payment_exists(payment_id):
                return emit("error", {"message": "Payment not found"})

            # Check if user has access to this payment
            if not PaymentService.user_has_access_to_payment(
                current_user.id, payment_id
            ):
                return emit("error", {"message": "Access denied"})

            try:
                payment = PaymentService.get_payment(payment_id)
                emit(
                    "payment_update",
                    {
                        "payment_id": payment_id,
                        "status": payment.status.value,
                        "amount": payment.amount,
                        "updated_at": payment.updated_at.isoformat(),
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
            except Exception as e:
                logger.error(f"Error getting payment status: {str(e)}")
                emit("error", {"message": "Failed to get payment status"})

        except Exception as e:
            logger.error(f"Payment status error: {e}")
            emit("error", {"message": "Failed to get payment status"})

    # ==================== SELLER ORDER MANAGEMENT ====================
    def on_join_seller_orders(self, data):
        """Join room for seller order updates with validation"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            if not current_user.is_seller:
                return emit("error", {"message": "Seller access required"})

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
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
            except Exception as e:
                logger.error(f"Error getting seller stats: {str(e)}")
                emit("error", {"message": "Failed to get seller stats"})

        except Exception as e:
            logger.error(f"Join seller orders error: {e}")
            emit("error", {"message": "Failed to join seller orders"})

    def on_leave_seller_orders(self, data):
        """Leave seller orders room"""
        try:
            if current_user.is_authenticated and current_user.is_seller:
                leave_room(f"seller_orders_{current_user.seller_account.id}")
        except Exception as e:
            logger.error(f"Leave seller orders error: {e}")

    # ==================== UTILITY ====================
    def on_ping(self, data):
        """Keep connection alive with rate limiting"""
        from main.sockets import SocketManager

        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Rate limiting
            if not self._check_rate_limit("ping", current_user.id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Refresh online status using centralized manager
            SocketManager.mark_user_online(current_user.id, "orders")

            emit(
                "pong",
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "user_id": current_user.id,
                },
            )

        except Exception as e:
            logger.error(f"Order ping error: {e}")
            emit("error", {"message": "Ping failed"})

    def on_get_order_history(self, data):
        """Handle get order history request"""
        try:
            if not current_user.is_authenticated:
                return emit("error", {"message": "Unauthorized"})

            # Parse pagination parameters
            page = data.get("page", 1)
            per_page = min(data.get("per_page", 20), 50)  # Max 50 per page
            status_filter = data.get("status")

            from app.orders.services import OrderService

            orders = OrderService.list_user_orders(
                current_user.id, page=page, per_page=per_page, status=status_filter
            )

            emit(
                "order_history",
                {
                    "orders": orders["items"],
                    "pagination": orders["pagination"],
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Error getting order history: {str(e)}")
            emit("error", {"message": "Failed to get order history"})
