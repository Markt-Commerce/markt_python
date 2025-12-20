# python imports
import logging
import requests
import hashlib
import hmac
from datetime import datetime
from typing import Any, Dict, Optional

# package imports
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

# project imports
from external.redis import redis_client
from app.libs.session import session_scope
from app.libs.errors import (
    NotFoundError,
    ValidationError,
    ConflictError,
    APIError,
    ForbiddenError,
)

# app imports
from .models import Payment, Transaction, PaymentStatus, PaymentMethod
from app.orders.models import Order, OrderStatus
from app.users.models import User, Seller
from app.notifications.services import NotificationService
from app.notifications.models import NotificationType

logger = logging.getLogger(__name__)


class PaymentService:
    """Payment service with Paystack integration for Nigeria"""

    # Paystack configuration
    PAYSTACK_BASE_URL = "https://api.paystack.co"
    PAYSTACK_SECRET_KEY = None  # Set from config
    PAYSTACK_PUBLIC_KEY = None  # Set from config

    # Cache configuration
    CACHE_EXPIRY = 1800  # 30 minutes
    PAYMENT_CACHE_KEY = "payment:{payment_id}"

    @classmethod
    def initialize_paystack(cls, secret_key: str, public_key: str):
        """Initialize Paystack configuration"""
        cls.PAYSTACK_SECRET_KEY = secret_key
        cls.PAYSTACK_PUBLIC_KEY = public_key
        logger.info("Paystack payment service initialized")

    @staticmethod
    def create_payment(
        order_id: str,
        amount: float,
        currency: str = "NGN",
        method: PaymentMethod = PaymentMethod.CARD,
        metadata: Optional[Dict] = None,
        idempotency_key: Optional[str] = None,
    ) -> Payment:
        """Create a new payment record"""
        import uuid

        with session_scope() as session:
            # Check idempotency if key provided
            if idempotency_key:
                existing_payment = (
                    session.query(Payment)
                    .filter_by(idempotency_key=idempotency_key)
                    .first()
                )
                if existing_payment:
                    return existing_payment

            # Validate order
            order = session.query(Order).get(order_id)
            if not order:
                raise NotFoundError("Order not found")

            # Accept both PENDING and PENDING_PAYMENT for backward compatibility
            if order.status not in (OrderStatus.PENDING, OrderStatus.PENDING_PAYMENT):
                raise ValidationError(
                    f"Order is not in pending payment status. Current status: {order.status.value}"
                )

            # Convert string method to enum if needed
            if isinstance(method, str):
                try:
                    method = PaymentMethod(method)
                except ValueError:
                    raise ValidationError(f"Invalid payment method: {method}")

            # Create payment record
            payment = Payment(
                order_id=order_id,
                amount=amount,
                currency=currency,
                method=method,
                status=PaymentStatus.PENDING,
                gateway_response={},
                idempotency_key=idempotency_key or str(uuid.uuid4()),
            )

            session.add(payment)
            session.flush()

            # Initialize with Paystack if card payment
            if method == PaymentMethod.CARD:
                PaymentService._initialize_paystack_transaction(payment, metadata)

            # Cache payment
            PaymentService._cache_payment(payment)

            return payment

    @staticmethod
    def process_payment(payment_id: str, payment_data: Dict[str, Any]) -> Payment:
        """Process payment with Paystack"""
        with session_scope() as session:
            payment = session.query(Payment).get(payment_id)
            if not payment:
                raise NotFoundError("Payment not found")

            if payment.status != PaymentStatus.PENDING:
                raise ValidationError("Payment is not in pending status")

            try:
                # Process with Paystack
                if payment.method == PaymentMethod.CARD:
                    result = PaymentService._process_paystack_payment(
                        payment, payment_data
                    )
                elif payment.method == PaymentMethod.BANK_TRANSFER:
                    result = PaymentService._process_bank_transfer(
                        payment, payment_data
                    )
                else:
                    raise ValidationError(
                        f"Unsupported payment method: {payment.method}"
                    )

                # Update payment status
                payment.status = result["status"]
                payment.transaction_id = result.get("transaction_id")
                payment.gateway_response = result.get("gateway_response", {})

                if result["status"] == PaymentStatus.COMPLETED:
                    payment.paid_at = datetime.utcnow()

                # Update order status to processing after payment succeeds
                order = session.query(Order).get(payment.order_id)
                if order:
                    # Move from PENDING_PAYMENT (or PENDING for backward compat) to PROCESSING
                    if order.status in (
                        OrderStatus.PENDING,
                        OrderStatus.PENDING_PAYMENT,
                    ):
                        order.status = OrderStatus.PROCESSING

                        # Reduce inventory for all order items
                        from app.products.services import ProductService

                        ProductService.reduce_inventory_for_order(order.items)

                        # Create transaction record
                        transaction = Transaction(
                            user_id=order.buyer.user_id,
                            seller_id=order.items[0].product.seller_id
                            if order.items
                            else None,
                            amount=payment.amount,
                            type="debit",
                            reference=f"PAY_{payment.id}",
                            status="completed",
                            payment_metadata=result.get("gateway_response", {}),
                        )
                        session.add(transaction)

                session.flush()

                # Send notifications
                PaymentService._send_payment_notifications(payment, result["status"])

                # Queue async real-time event (non-blocking)
                try:
                    from app.realtime.event_manager import EventManager

                    EventManager.emit_to_order(
                        payment.order_id,
                        "payment_confirmed",
                        {
                            "payment_id": payment.id,
                            "order_id": payment.order_id,
                            "user_id": payment.order.buyer.user_id
                            if payment.order and payment.order.buyer
                            else None,
                            "amount": payment.amount,
                            "status": payment.status.value,
                            "transaction_id": payment.transaction_id,
                            "metadata": {
                                "method": payment.method.value
                                if payment.method
                                else None,
                                "order_number": payment.order.order_number
                                if payment.order
                                else None,
                            },
                        },
                    )
                except Exception as e:
                    logger.warning(f"Failed to queue payment_confirmed event: {e}")

                return payment

            except Exception as e:
                logger.error(f"Payment processing failed: {str(e)}")
                payment.status = PaymentStatus.FAILED
                payment.gateway_response = {"error": str(e)}
                session.flush()

                # Send failure notification
                PaymentService._send_payment_notifications(
                    payment, PaymentStatus.FAILED
                )
                raise APIError("Payment processing failed", 500)

    @staticmethod
    def verify_payment(payment_id: str) -> Dict[str, Any]:
        """Verify payment status with Paystack"""
        with session_scope() as session:
            payment = session.query(Payment).get(payment_id)
            if not payment:
                raise NotFoundError("Payment not found")

            if not payment.transaction_id:
                raise ValidationError("No transaction ID to verify")

            try:
                # Verify with Paystack
                response = requests.get(
                    f"{PaymentService.PAYSTACK_BASE_URL}/transaction/verify/{payment.transaction_id}",
                    headers={
                        "Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    if data["status"] and data["data"]["status"] == "success":
                        return {
                            "verified": True,
                            "amount": data["data"]["amount"] / 100,  # Convert from kobo
                            "gateway_response": data,
                        }
                    else:
                        return {"verified": False, "gateway_response": data}
                else:
                    raise APIError("Failed to verify payment with gateway", 500)

            except Exception as e:
                logger.error(f"Payment verification failed: {str(e)}")
                raise APIError("Payment verification failed", 500)

    @staticmethod
    def get_payment(payment_id: str) -> Payment:
        """Get payment by ID with caching"""
        # Try cache first
        cache_key = PaymentService.PAYMENT_CACHE_KEY.format(payment_id=payment_id)
        cached = redis_client.get(cache_key)
        if cached:
            # For now, return None if cached to force DB lookup
            # TODO: Implement proper cache deserialization
            pass

        with session_scope() as session:
            payment = (
                session.query(Payment)
                .options(joinedload(Payment.order))
                .get(payment_id)
            )

            if not payment:
                raise NotFoundError("Payment not found")

            # Cache for 30 minutes
            PaymentService._cache_payment(payment)
            return payment

    @staticmethod
    def list_user_payments(
        user_id: str, page: int = 1, per_page: int = 20
    ) -> Dict[str, Any]:
        """List payments for a user"""
        with session_scope() as session:
            # Get user's orders
            orders = session.query(Order).filter_by(buyer_id=user_id).all()
            order_ids = [order.id for order in orders]

            # Get payments for these orders
            payments = (
                session.query(Payment)
                .filter(Payment.order_id.in_(order_ids))
                .order_by(Payment.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )

            total = (
                session.query(Payment).filter(Payment.order_id.in_(order_ids)).count()
            )

            return {
                "payments": payments,
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page,
            }

    @staticmethod
    def handle_webhook(payload: Dict[str, Any], signature: str) -> bool:
        """Handle Paystack webhook"""
        try:
            # Verify webhook signature
            if not PaymentService._verify_webhook_signature(payload, signature):
                logger.warning("Invalid webhook signature")
                return False

            event = payload.get("event")
            data = payload.get("data", {})

            if event == "charge.success":
                return PaymentService._handle_successful_charge(data)
            elif event == "transfer.success":
                return PaymentService._handle_successful_transfer(data)
            elif event == "charge.failed":
                return PaymentService._handle_failed_charge(data)
            else:
                logger.info(f"Unhandled webhook event: {event}")
                return True

        except Exception as e:
            logger.error(f"Webhook handling failed: {str(e)}")
            return False

    # ==================== PRIVATE METHODS ====================

    @staticmethod
    def _initialize_paystack_transaction(
        payment: Payment, metadata: Optional[Dict] = None
    ):
        """Initialize Paystack transaction"""
        try:
            from main.config import settings

            order = payment.order
            buyer = order.buyer.user

            # Build callback URL using configured base URL
            base_url = settings.API_BASE_URL
            if not base_url:
                # Fallback: try to construct from request if available
                try:
                    from flask import request

                    if request:
                        base_url = f"{request.scheme}://{request.host}"
                except:
                    base_url = "http://localhost:8000"  # Final fallback

            callback_url = f"{base_url}/api/v1/payments/callback/{payment.id}"

            payload = {
                "amount": int(payment.amount * 100),  # Convert to kobo
                "email": buyer.email,
                "currency": payment.currency,
                "reference": f"PAY_{payment.id}",
                "callback_url": callback_url,
                "metadata": {
                    "payment_id": payment.id,
                    "order_id": payment.order_id,
                    "buyer_id": buyer.id,
                    **(metadata or {}),
                },
            }

            response = requests.post(
                f"{PaymentService.PAYSTACK_BASE_URL}/transaction/initialize",
                json=payload,
                headers={
                    "Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"
                },
            )

            if response.status_code == 200:
                data = response.json()
                payment.gateway_response = data
                payment.transaction_id = data["data"]["reference"]
            else:
                raise APIError("Failed to initialize payment", 500)

        except Exception as e:
            logger.error(f"Paystack initialization failed: {str(e)}")
            raise APIError("Payment initialization failed", 500)

    @staticmethod
    def _process_paystack_payment(
        payment: Payment, payment_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process payment with Paystack"""
        try:
            # For card payments, we need to charge the card
            payload = {
                "amount": int(payment.amount * 100),
                "email": payment.order.buyer.user.email,
                "currency": payment.currency,
                "reference": payment.transaction_id,
                "authorization_code": payment_data.get("authorization_code"),
                "metadata": {"payment_id": payment.id, "order_id": payment.order_id},
            }

            response = requests.post(
                f"{PaymentService.PAYSTACK_BASE_URL}/transaction/charge_authorization",
                json=payload,
                headers={
                    "Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"
                },
            )

            if response.status_code == 200:
                data = response.json()
                if data["status"] and data["data"]["status"] == "success":
                    return {
                        "status": PaymentStatus.COMPLETED,
                        "transaction_id": data["data"]["reference"],
                        "gateway_response": data,
                    }
                else:
                    return {"status": PaymentStatus.FAILED, "gateway_response": data}
            else:
                raise APIError("Payment processing failed", 500)

        except Exception as e:
            logger.error(f"Paystack payment processing failed: {str(e)}")
            raise APIError("Payment processing failed", 500)

    @staticmethod
    def _process_bank_transfer(
        payment: Payment, payment_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process bank transfer payment using Paystack's Charge API.

        The typical flow is:
        1. Frontend collects bank details securely (e.g. account number + bank code).
        2. Frontend sends a `bank` object in `payment_data` to this endpoint.
        3. We call Paystack `/charge` with those details and mark the payment as
           PENDING while we wait for webhook confirmation (`charge.success`).
        """
        try:
            bank_details = payment_data.get("bank")
            if not bank_details:
                raise ValidationError(
                    "Bank details are required for bank transfer payments"
                )

            order = payment.order
            if not order or not order.buyer or not order.buyer.user:
                raise ValidationError("Associated order/buyer information is missing")

            payload: Dict[str, Any] = {
                "amount": int(payment.amount * 100),  # Convert to kobo
                "email": order.buyer.user.email,
                "currency": payment.currency,
                "bank": bank_details,
                "metadata": {
                    "payment_id": payment.id,
                    "order_id": payment.order_id,
                    "buyer_id": order.buyer.user.id,
                    "method": "bank_transfer",
                },
            }

            # Reuse the same reference style used elsewhere so we can match
            # incoming webhooks back to this payment.
            payload["reference"] = payment.transaction_id or f"PAY_{payment.id}"

            response = requests.post(
                f"{PaymentService.PAYSTACK_BASE_URL}/charge",
                json=payload,
                headers={
                    "Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"
                },
            )

            if response.status_code != 200:
                logger.error(
                    "Paystack bank transfer charge failed with status %s: %s",
                    response.status_code,
                    response.text,
                )
                raise APIError("Bank transfer initialization failed", 500)

            data = response.json()

            # For bank payments Paystack typically returns a pending status while
            # waiting for customer action/OTP. We keep our Payment in PENDING and
            # rely on the webhook (`charge.success`) to mark it COMPLETED.
            if not data.get("status"):
                return {
                    "status": PaymentStatus.FAILED,
                    "gateway_response": data,
                }

            reference = (
                data.get("data", {}).get("reference")
                or data.get("data", {}).get("id")
                or payload["reference"]
            )

            return {
                "status": PaymentStatus.PENDING,
                "transaction_id": reference,
                "gateway_response": data,
            }

        except APIError:
            # Already logged / wrapped, just bubble up
            raise
        except Exception as e:
            logger.error(f"Bank transfer processing failed: {str(e)}")
            raise APIError("Bank transfer processing failed", 500)

    @staticmethod
    def _verify_webhook_signature(payload: Dict[str, Any], signature: str) -> bool:
        """Verify Paystack webhook signature"""
        try:
            # Create HMAC SHA512 hash
            computed_signature = hmac.new(
                PaymentService.PAYSTACK_SECRET_KEY.encode("utf-8"),
                str(payload).encode("utf-8"),
                hashlib.sha512,
            ).hexdigest()

            return hmac.compare_digest(computed_signature, signature)
        except Exception:
            return False

    @staticmethod
    def _handle_successful_charge(data: Dict[str, Any]) -> bool:
        """Handle successful charge webhook"""
        try:
            reference = data.get("reference")
            if not reference:
                return False

            with session_scope() as session:
                payment = (
                    session.query(Payment).filter_by(transaction_id=reference).first()
                )
                if not payment:
                    logger.warning(f"Payment not found for reference: {reference}")
                    return False

                payment.status = PaymentStatus.COMPLETED
                payment.paid_at = datetime.utcnow()
                payment.gateway_response = data

                # Update order status to processing after payment succeeds
                order = session.query(Order).get(payment.order_id)
                if order:
                    # Move from PENDING_PAYMENT (or PENDING for backward compat) to PROCESSING
                    if order.status in (
                        OrderStatus.PENDING,
                        OrderStatus.PENDING_PAYMENT,
                    ):
                        order.status = OrderStatus.PROCESSING

                    # Reduce inventory for all order items
                    from app.products.services import ProductService

                    ProductService.reduce_inventory_for_order(order.items)

                session.flush()

                # Send notifications
                PaymentService._send_payment_notifications(
                    payment, PaymentStatus.COMPLETED
                )

                # Queue async real-time event (non-blocking)
                try:
                    from app.realtime.event_manager import EventManager

                    EventManager.emit_to_order(
                        payment.order_id,
                        "payment_confirmed",
                        {
                            "payment_id": payment.id,
                            "order_id": payment.order_id,
                            "user_id": payment.order.buyer.user_id
                            if payment.order and payment.order.buyer
                            else None,
                            "amount": payment.amount,
                            "status": payment.status.value,
                            "transaction_id": payment.transaction_id,
                            "metadata": {
                                "method": payment.method.value
                                if payment.method
                                else None,
                                "order_number": payment.order.order_number
                                if payment.order
                                else None,
                            },
                        },
                    )
                except Exception as e:
                    logger.warning(f"Failed to queue payment_confirmed event: {e}")

                return True

        except Exception as e:
            logger.error(f"Failed to handle successful charge: {str(e)}")
            return False

    @staticmethod
    def _handle_failed_charge(data: Dict[str, Any]) -> bool:
        """Handle failed charge webhook"""
        try:
            reference = data.get("reference")
            if not reference:
                return False

            with session_scope() as session:
                payment = (
                    session.query(Payment).filter_by(transaction_id=reference).first()
                )
                if not payment:
                    return False

                payment.status = PaymentStatus.FAILED
                payment.gateway_response = data
                session.flush()

                # Send failure notification
                PaymentService._send_payment_notifications(
                    payment, PaymentStatus.FAILED
                )

                # Emit real-time update
                PaymentService._emit_payment_update(payment)

                return True

        except Exception as e:
            logger.error(f"Failed to handle failed charge: {str(e)}")
            return False

    @staticmethod
    def _handle_successful_transfer(data: Dict[str, Any]) -> bool:
        """Handle successful transfer webhook (for payouts)"""
        # Implementation for seller payouts
        return True

    @staticmethod
    def _send_payment_notifications(payment: Payment, status: PaymentStatus):
        """Send payment notifications"""
        try:
            order = payment.order
            buyer = order.buyer.user

            if status == PaymentStatus.COMPLETED:
                # Notify buyer
                NotificationService.create_notification(
                    user_id=buyer.id,
                    notification_type=NotificationType.PAYMENT_SUCCESS,
                    reference_type="payment",
                    reference_id=payment.id,
                    metadata_={
                        "order_id": payment.order_id,
                        "amount": payment.amount,
                        "currency": payment.currency,
                    },
                )

                # Notify seller
                if order.items:
                    seller_id = order.items[0].product.seller.user_id
                    NotificationService.create_notification(
                        user_id=seller_id,
                        notification_type=NotificationType.PAYMENT_SUCCESS,
                        reference_type="payment",
                        reference_id=payment.id,
                        metadata_={
                            "order_id": payment.order_id,
                            "amount": payment.amount,
                            "currency": payment.currency,
                        },
                    )

            elif status == PaymentStatus.FAILED:
                # Notify buyer of failure
                NotificationService.create_notification(
                    user_id=buyer.id,
                    notification_type=NotificationType.PAYMENT_FAILED,
                    reference_type="payment",
                    reference_id=payment.id,
                    metadata_={
                        "order_id": payment.order_id,
                        "amount": payment.amount,
                        "currency": payment.currency,
                    },
                )

        except Exception as e:
            logger.error(f"Failed to send payment notifications: {str(e)}")

    @staticmethod
    def _emit_payment_update(payment: Payment):
        """Emit real-time payment update using centralized emission"""
        try:
            from main.sockets import emit_to_room

            # Emit to buyer
            buyer_room = f"buyer_{payment.order.buyer.id}"
            emit_to_room(
                buyer_room,
                "payment_update",
                {
                    "payment_id": payment.id,
                    "status": payment.status.value,
                    "amount": payment.amount,
                    "updated_at": payment.updated_at.isoformat(),
                },
                namespace="/orders",
            )

            # Emit to seller if applicable
            if payment.order.items:
                seller_room = f"seller_{payment.order.items[0].product.seller.id}"
                emit_to_room(
                    seller_room,
                    "payment_update",
                    {
                        "payment_id": payment.id,
                        "status": payment.status.value,
                        "amount": payment.amount,
                        "updated_at": payment.updated_at.isoformat(),
                    },
                    namespace="/orders",
                )

        except Exception as e:
            logger.error(f"Failed to emit payment update: {str(e)}")

    @staticmethod
    def _cache_payment(payment: Payment):
        """Cache payment data"""
        try:
            cache_key = PaymentService.PAYMENT_CACHE_KEY.format(payment_id=payment.id)
            # Convert payment object to JSON-serializable dict
            payment_data = {
                "id": payment.id,
                "order_id": payment.order_id,
                "amount": payment.amount,
                "currency": payment.currency,
                "method": payment.method.value if payment.method else None,
                "status": payment.status.value if payment.status else None,
                "transaction_id": payment.transaction_id,
                "gateway_response": payment.gateway_response,
                "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
                "created_at": payment.created_at.isoformat()
                if payment.created_at
                else None,
                "updated_at": payment.updated_at.isoformat()
                if payment.updated_at
                else None,
            }
            redis_client.setex(
                cache_key, PaymentService.CACHE_EXPIRY, str(payment_data)
            )
        except Exception as e:
            logger.warning(f"Failed to cache payment: {str(e)}")

    @staticmethod
    def _invalidate_payment_cache(payment_id: str):
        """Invalidate payment cache"""
        try:
            cache_key = PaymentService.PAYMENT_CACHE_KEY.format(payment_id=payment_id)
            redis_client.delete(cache_key)
        except Exception as e:
            logger.warning(f"Failed to invalidate payment cache: {str(e)}")
