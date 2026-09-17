import logging
from datetime import datetime, timedelta
from typing import Dict, List

from main.workers import celery_app
from external.redis import redis_client
from app.libs.session import session_scope, read_scope

from .models import Notification, NotificationType

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, queue="notifications")
def deliver_notification(self, notification_data: Dict, channels: List[str]):
    """
    Asynchronously deliver notification via specified channels
    """
    try:
        user_id = notification_data["user_id"]
        notification_data["type"]

        for channel in channels:
            try:
                if channel == "push":  # DeliveryChannel.PUSH.value
                    send_push_notification.delay(notification_data)
                elif channel == "email":  # DeliveryChannel.EMAIL.value
                    send_email_notification.delay(notification_data)
                elif channel == "websocket":  # DeliveryChannel.WEBSOCKET.value
                    # Use centralized emission method
                    from main.sockets import emit_to_user

                    # Fallback WebSocket delivery (if immediate delivery failed)
                    success = emit_to_user(
                        user_id,
                        "notification",
                        notification_data,
                        namespace="/notifications",
                    )

                    if success:
                        # Update unread count
                        unread_count = get_unread_count(user_id)
                        emit_to_user(
                            user_id,
                            "unread_count_update",
                            {"count": unread_count},
                            namespace="/notifications",
                        )

            except Exception as channel_error:
                logger.error(
                    f"Failed to deliver via {channel} for user {user_id}: {str(channel_error)}"
                )
                # Continue with other channels even if one fails

        logger.info(
            f"Async notification delivery completed for user {user_id} via channels: {channels}"
        )

    except Exception as e:
        logger.error(f"Notification delivery task failed: {str(e)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2**self.request.retries))
        raise


@celery_app.task(bind=True, queue="notifications")
def send_push_notification(self, notification_data: Dict):
    """Send push notification to the user's registered devices via Expo Push."""
    try:
        from .services import PushService

        user_id = notification_data.get("user_id")
        if not user_id:
            return
        title = notification_data.get("title") or "Markt"
        body = notification_data.get("message") or notification_data.get("body") or ""
        PushService.send_to_user(
            user_id,
            title,
            body,
            {
                "type": notification_data.get("type"),
                "reference_type": notification_data.get("reference_type"),
                "reference_id": notification_data.get("reference_id"),
                # An order notification without its status lands everyone on
                # the order summary. "A rider has picked it up" should open
                # tracking; "delivered" should not.
                "status": (notification_data.get("metadata_") or {}).get("status"),
            },
        )
        logger.info(
            f"Push notification dispatched for notification {notification_data.get('id')}"
        )
    except Exception as e:
        logger.error(f"Push notification failed: {str(e)}")


def _order_email_data(notification_data: Dict, meta: Dict) -> Dict:
    """Fill in what the order emails read, from the DB where needed.

    The previous version passed `reference_id` as `order_number`. That is an
    order *id* (ORD_xxxx), so every order email showed the buyer an internal
    identifier they cannot quote at anyone, and `items` was only ever present
    if the caller happened to include it -- which no caller did, so the
    confirmation email listed nothing bought.
    """
    data = {
        "order_number": meta.get("order_number", ""),
        "status": meta.get("status", ""),
        "amount": meta.get("amount", 0),
        "total": meta.get("total", meta.get("amount", 0)),
        "items": meta.get("items", []),
        "buyer_name": meta.get("buyer_name", ""),
        "delivery_address": meta.get("delivery_address", ""),
        "rider_name": meta.get("rider_name", ""),
        "eta": meta.get("eta", ""),
        "reference": meta.get("reference", ""),
        "method": meta.get("method", ""),
        "reason": meta.get("reason", ""),
    }

    order_id = meta.get("order_id") or notification_data.get("reference_id")
    if not order_id or not str(order_id).startswith("ORD_"):
        return data

    # Hydrate anything the emitter did not carry. Best-effort: an email with
    # the order number missing is worse than one without a line-item table,
    # but neither is worth failing the send over.
    try:
        from app.orders.models import Order

        with read_scope() as session:
            order = session.query(Order).get(order_id)
            if not order:
                return data
            data["order_number"] = data["order_number"] or order.order_number
            data["total"] = data["total"] or order.total
            data["status"] = data["status"] or (
                order.status.value if order.status else ""
            )
            if not data["items"]:
                data["items"] = [
                    {
                        "product_name": (item.product.name if item.product else "Item"),
                        "quantity": item.quantity,
                        "price": item.price,
                    }
                    for item in order.items
                ]
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not hydrate order %s for email: %s", order_id, e)

    return data


@celery_app.task(bind=True, queue="notifications")
def send_email_notification(self, notification_data: Dict):
    """Send email notification for important alerts"""
    try:
        from app.libs.email_service import email_service
        from app.users.models import User

        user_id = notification_data["user_id"]
        notification_type = notification_data["type"]

        # Get the recipient's email.
        #
        # A rider is not a User: they live in delivery_users with a DEL_ id,
        # have no UserSettings row, and their address is verified by the OTP
        # they signed in with rather than a separate confirmation step.
        # Read the address *inside* the scope and keep the string, not the
        # instance. session_scope commits on exit and SQLAlchemy expires every
        # object it loaded, so `user.email` afterwards is either a second
        # SELECT or a DetachedInstanceError -- and the surrounding
        # `except Exception` would log that as "email notification failed"
        # rather than as the bug it is.
        recipient_email = None
        with session_scope() as session:
            if str(user_id).startswith("DEL_"):
                from app.deliveries.models import DeliveryUser

                rider = session.query(DeliveryUser).get(user_id)
                if not rider or not rider.email:
                    logger.warning("Rider %s has no email address", user_id)
                    return
                recipient_email = rider.email
            else:
                user = session.query(User).get(user_id)
                if not user or not user.email_verified:
                    logger.warning(f"User {user_id} not found or email not verified")
                    return

                # Check user email notification settings
                if user.settings and not user.settings.email_notifications:
                    logger.info(f"Email notifications disabled for user {user_id}")
                    return
                recipient_email = user.email

        # Map notification types to email methods
        email_methods = {
            NotificationType.ORDER_PLACED.value: email_service.send_order_confirmation_email,
            NotificationType.ORDER_UPDATE.value: email_service.send_order_status_update_email,
            NotificationType.PAYMENT_SUCCESS.value: email_service.send_payment_success_email,
            NotificationType.PAYMENT_FAILED.value: email_service.send_payment_failed_email,
        }

        email_method = email_methods.get(notification_type)
        if email_method:
            meta = notification_data.get("metadata_") or {}

            # A seller's "you sold something" email is not the buyer's "we
            # have your order" email, and both hang off ORDER_PLACED.
            if notification_type == NotificationType.ORDER_PLACED.value and (
                meta.get("role") == "seller"
            ):
                email_method = email_service.send_seller_order_notification_email

            email_data = _order_email_data(notification_data, meta)

            success = email_method(recipient_email, email_data)
            if success:
                logger.info(
                    f"Email notification sent for notification {notification_data['id']}"
                )
            else:
                logger.error(
                    f"Failed to send email notification for notification {notification_data['id']}"
                )
        else:
            logger.info(
                f"No email method configured for notification type {notification_type}"
            )

    except Exception as e:
        logger.error(f"Email notification failed: {str(e)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2**self.request.retries))


@celery_app.task(queue="notifications")
def cleanup_old_notifications():
    """Clean up old read notifications (keep for 30 days)"""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        with session_scope() as session:
            deleted = (
                session.query(Notification)
                .filter(
                    Notification.is_read == True, Notification.created_at < cutoff_date
                )
                .delete()
            )
            session.commit()
            logger.info(f"Cleaned up {deleted} old notifications")
    except Exception as e:
        logger.error(f"Notification cleanup failed: {str(e)}")


def get_unread_count(user_id: str) -> int:
    """Get unread notification count for user"""
    try:
        with session_scope() as session:
            return (
                session.query(Notification)
                .filter(Notification.user_id == user_id, Notification.is_read == False)
                .count()
            )
    except Exception as e:
        logger.error(f"Error getting unread count: {str(e)}")
        return 0


def _is_user_online(user_id: str) -> bool:
    """Check if user is currently online via SocketIO"""
    try:
        # Check if user has active socket connections
        return redis_client.exists(f"online_users:{user_id}")
    except Exception:
        return False


@celery_app.task(queue="analytics")
def send_seller_analytics_reports():
    """Send monthly/quarterly analytics reports to sellers"""
    try:
        from app.libs.email_service import email_service
        from app.users.models import User, Seller
        from app.orders.models import Order, OrderStatus
        from app.products.models import Product
        from sqlalchemy import func
        from datetime import datetime, timedelta

        # Get current period
        now = datetime.utcnow()
        if now.month in [3, 6, 9, 12]:  # Quarterly reports
            period = f"Q{(now.month // 3)} {now.year}"
            start_date = now.replace(day=1) - timedelta(days=90)
        else:  # Monthly reports
            period = f"{now.strftime('%B %Y')}"
            start_date = now.replace(day=1)

        with session_scope() as session:
            # Get all active sellers
            sellers = session.query(Seller).filter(Seller.is_active == True).all()

            for seller in sellers:
                try:
                    # Get seller's user info
                    user = session.query(User).get(seller.user_id)
                    if not user or not user.email_verified:
                        continue

                    # Check if user wants email notifications
                    if user.settings and not user.settings.email_notifications:
                        continue

                    # Calculate analytics
                    from app.orders.models import OrderItem

                    orders = (
                        session.query(Order)
                        .join(Order.items)
                        .filter(
                            OrderItem.seller_id == seller.id,
                            Order.created_at >= start_date,
                            Order.status.in_(
                                [
                                    OrderStatus.PROCESSING,
                                    OrderStatus.SHIPPED,
                                    OrderStatus.DELIVERED,
                                ]
                            ),
                        )
                        .all()
                    )

                    total_sales = sum(order.total for order in orders)
                    total_orders = len(orders)
                    total_products = (
                        session.query(Product)
                        .filter(
                            Product.seller_id == seller.id, Product.is_active == True
                        )
                        .count()
                    )

                    # Get top products
                    top_products = (
                        session.query(
                            Product.name,
                            func.sum(OrderItem.quantity).label("sales"),
                            func.sum(OrderItem.quantity * OrderItem.price).label(
                                "revenue"
                            ),
                        )
                        .join(OrderItem)
                        .join(Order)
                        .filter(
                            Product.seller_id == seller.id,
                            Order.created_at >= start_date,
                            Order.status.in_(
                                [
                                    OrderStatus.PROCESSING,
                                    OrderStatus.SHIPPED,
                                    OrderStatus.DELIVERED,
                                ]
                            ),
                        )
                        .group_by(Product.id, Product.name)
                        .order_by(func.sum(OrderItem.quantity * OrderItem.price).desc())
                        .limit(5)
                        .all()
                    )

                    # Prepare report data
                    # The same window, one period earlier. A figure with
                    # nothing to compare it against is not information -- the
                    # template prints "12 more than the month before" only
                    # when this is here, and nothing at all when it is not.
                    previous_start = start_date - (now - start_date)
                    previous_orders = (
                        session.query(Order)
                        .join(OrderItem, OrderItem.order_id == Order.id)
                        .filter(
                            OrderItem.seller_id == seller.id,
                            Order.created_at >= previous_start,
                            Order.created_at < start_date,
                            Order.status != OrderStatus.CANCELLED,
                        )
                        .all()
                    )

                    report_data = {
                        "period": period,
                        "shop_name": seller.shop_name,
                        "previous": {
                            "total_sales": float(
                                sum(o.total or 0 for o in previous_orders)
                            ),
                            "total_orders": len(previous_orders),
                        },
                        "total_sales": total_sales,
                        "total_orders": total_orders,
                        "total_products": total_products,
                        "top_products": [
                            {
                                "name": product.name,
                                "sales": int(product.sales),
                                "revenue": float(product.revenue),
                            }
                            for product in top_products
                        ],
                    }

                    # Send analytics report
                    success = email_service.send_seller_analytics_report(
                        user.email, report_data
                    )
                    if success:
                        logger.info(
                            f"Analytics report sent to seller {seller.id} for period {period}"
                        )
                    else:
                        logger.error(
                            f"Failed to send analytics report to seller {seller.id}"
                        )

                except Exception as e:
                    logger.error(
                        f"Error processing analytics for seller {seller.id}: {str(e)}"
                    )
                    continue

    except Exception as e:
        logger.error(f"Analytics report task failed: {str(e)}")
