import logging
from datetime import datetime, timedelta
from typing import Dict, List

from main.workers import celery_app
from external.redis import redis_client
from app.libs.session import session_scope

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
        from app.users.models import User

        user_id = notification_data.get("user_id")
        if not user_id:
            return
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if user and user.settings and not user.settings.push_notifications:
                logger.info("Push notifications disabled for user %s", user_id)
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
            },
        )
        logger.info(
            f"Push notification dispatched for notification {notification_data.get('id')}"
        )
    except Exception as e:
        logger.error(f"Push notification failed: {str(e)}")


@celery_app.task(bind=True, queue="notifications")
def send_email_notification(self, notification_data: Dict):
    """Deliver every configured email event through the common branded template.

    Transactional mail is not suppressed by the optional marketing/email
    preference. Promotional mail requires the explicit marketing opt-in.
    """
    try:
        from app.libs.email_service import email_service
        from app.users.models import User

        user_id = notification_data["user_id"]
        notification_type = notification_data["type"]

        # Get user email
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not user or not user.email_verified:
                logger.warning(f"User {user_id} not found or email not verified")
                return

        notification_enum = next(
            (item for item in NotificationType if item.value == notification_type),
            None,
        )
        if not notification_enum:
            logger.warning(
                "Unknown notification type %s; email skipped", notification_type
            )
            return
        from app.notifications.services import NotificationService

        transactional = NotificationService.is_transactional_email(notification_enum)
        if notification_enum == NotificationType.PROMOTIONAL:
            if not user.settings or not user.settings.marketing_notifications:
                logger.info("Promotional email disabled for user %s", user_id)
                return
        elif (
            user.settings
            and not user.settings.email_notifications
            and not transactional
        ):
            logger.info("Optional email notifications disabled for user %s", user_id)
            return

        metadata = notification_data.get("metadata_", {})
        if notification_enum == NotificationType.PROMOTIONAL:
            success = email_service.send_promotional_campaign_email(
                user.email,
                {
                    **metadata,
                    "subject": notification_data.get("title"),
                    "headline": notification_data.get("title"),
                    "subheadline": notification_data.get("message"),
                },
            )
        elif notification_enum in (
            NotificationType.ORDER_UPDATE,
            NotificationType.SHIPMENT_UPDATE,
        ) and metadata.get("tracking_steps"):
            success = email_service.send_order_tracking_email(
                user.email,
                {
                    **metadata,
                    "order_number": notification_data.get("reference_id"),
                    "status": metadata.get("status", notification_data.get("title")),
                },
            )
        else:
            success = email_service.send_notification_email(
                email=user.email,
                title=notification_data.get("title", "Markt notification"),
                message=notification_data.get("message", ""),
                notification_type=notification_type,
                metadata=metadata,
                transactional=transactional,
                sender_profile=(
                    "marketing"
                    if notification_enum == NotificationType.PROMOTIONAL
                    else "transactional"
                    if transactional
                    else "notification"
                ),
            )
        if success:
            logger.info(
                "Email notification sent for notification %s",
                notification_data.get("id"),
            )
        else:
            logger.error(
                "Failed to send email notification for notification %s",
                notification_data.get("id"),
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
                    report_data = {
                        "period": period,
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
