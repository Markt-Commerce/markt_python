import logging
from datetime import datetime
from flask_socketio import Namespace, emit, join_room, leave_room
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
            emit(
                "connected",
                {"status": "connected", "message": "Connected to orders namespace"},
            )
            logger.info("Client connected to orders namespace")

        except Exception as e:
            logger.error(f"Order connection error: {e}")
            emit("error", {"message": "Connection failed"})

    def on_disconnect(self):
        """Handle client disconnection"""
        from main.sockets import SocketManager

        try:
            logger.info("Client disconnected from orders namespace")
        except Exception as e:
            logger.error(f"Order disconnection error: {e}")

    # ==================== ORDER TRACKING ====================
    def on_join_order(self, data):
        """Join room for specific order updates with validation"""
        try:
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Rate limiting
            if not self._check_rate_limit("join_order", user_id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["order_id", "user_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            order_id = data.get("order_id")

            # Validate order exists and user has access
            from app.orders.services import OrderService

            if not OrderService.order_exists(order_id):
                return emit("error", {"message": "Order not found"})

            # Check if user has access to this order
            if not OrderService.user_has_access_to_order(user_id, order_id):
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
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["order_id", "user_id"])
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
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Rate limiting
            if not self._check_rate_limit("payment_status", user_id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["payment_id", "user_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            payment_id = data.get("payment_id")

            # Validate payment exists and user has access
            from app.payments.services import PaymentService

            if not PaymentService.payment_exists(payment_id):
                return emit("error", {"message": "Payment not found"})

            # Check if user has access to this payment
            if not PaymentService.user_has_access_to_payment(user_id, payment_id):
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
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Data validation
            is_valid, error_msg = self._validate_data(data, ["user_id"])
            if not is_valid:
                return emit("error", {"message": error_msg})

            # Check seller account via user service (or extend validation logic)
            from app.users.services import UserService

            user = UserService.get_user_by_id(user_id)
            if not user or not hasattr(user, "seller_account"):
                return emit("error", {"message": "Seller access required"})

            join_room(f"seller_orders_{user.seller_account.id}")

            # Get pending orders count
            from app.orders.services import SellerOrderService

            try:
                stats = SellerOrderService.get_seller_order_stats(
                    user.seller_account.id
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
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Check seller account and leave room
            from app.users.services import UserService

            user = UserService.get_user_by_id(user_id)
            if user and hasattr(user, "seller_account"):
                leave_room(f"seller_orders_{user.seller_account.id}")
        except Exception as e:
            logger.error(f"Leave seller orders error: {e}")

    # ==================== UTILITY ====================
    def on_ping(self, data):
        """Keep connection alive with rate limiting"""
        from main.sockets import SocketManager

        try:
            # Use user_id from client instead of current_user
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Rate limiting
            if not self._check_rate_limit("ping", user_id):
                return emit("error", {"message": "Rate limit exceeded"})

            # Refresh online status using centralized manager
            SocketManager.mark_user_online(user_id, "orders")

            emit(
                "pong",
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "user_id": user_id,
                },
            )

        except Exception as e:
            logger.error(f"Order ping error: {e}")
            emit("error", {"message": "Ping failed"})

    def on_get_order_history(self, data):
        """Handle get order history request"""
        try:
            user_id = data.get("user_id")
            if not user_id:
                return emit("error", {"message": "User ID required"})

            # Parse pagination parameters
            page = data.get("page", 1)
            per_page = min(data.get("per_page", 20), 50)  # Max 50 per page
            status_filter = data.get("status")

            from app.orders.services import OrderService

            orders = OrderService.list_user_orders(
                user_id, page=page, per_page=per_page, status=status_filter
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
