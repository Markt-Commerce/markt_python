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
from app.orders.models import Order, OrderStatus, OrderItem
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
    def _resolve_order_payment_amount(
        order: Order, client_amount: Optional[float]
    ) -> float:
        """Derive the payable amount from the order; optionally validate client input."""
        expected = order.total if order.total is not None else order.subtotal
        if expected is None:
            raise ValidationError("Order total is not set")
        if client_amount is not None and abs(client_amount - expected) > 0.01:
            raise ValidationError(
                f"Payment amount {client_amount} does not match order total {expected}"
            )
        return expected

    @staticmethod
    def complete_payment(
        *,
        payment_id: Optional[str] = None,
        reference: Optional[str] = None,
        gateway_response: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Idempotently mark a payment completed and advance the order lifecycle."""
        if not payment_id and not reference:
            return False

        with session_scope() as session:
            # Row-lock the payment: Paystack's charge.success webhook and the
            # browser callback's verify both land here within the same second.
            # Without the lock both read status=PENDING, both reduce inventory,
            # and the loser can blow up with "Insufficient stock" — turning a
            # gateway-confirmed success into a failed redirect for the user.
            # (No joinedload here: FOR UPDATE can't be combined with the outer
            # joins eager loading generates; relations lazy-load fine below.)
            query = session.query(Payment).with_for_update()
            if payment_id:
                payment = query.filter_by(id=payment_id).first()
            else:
                payment = query.filter_by(transaction_id=reference).first()

            if not payment:
                logger.warning(
                    "complete_payment: payment not found (id=%s, ref=%s)",
                    payment_id,
                    reference,
                )
                return False

            already_completed = payment.status == PaymentStatus.COMPLETED

            if not already_completed:
                payment.status = PaymentStatus.COMPLETED
                payment.paid_at = datetime.utcnow()
                if gateway_response is not None:
                    payment.gateway_response = gateway_response

            order = payment.order
            if order and order.status in (
                OrderStatus.PENDING,
                OrderStatus.PENDING_PAYMENT,
            ):
                order.status = OrderStatus.READY_FOR_DELIVERY
                if not order.order_number:
                    order.order_number = order.generate_order_number()

                for item in order.items:
                    if item.status == OrderItem.Status.PENDING:
                        item.status = OrderItem.Status.PROCESSING

                if not already_completed:
                    from app.products.services import ProductService

                    ProductService.reduce_inventory_for_order(order.items)

                    existing_txn = (
                        session.query(Transaction)
                        .filter_by(reference=f"PAY_{payment.id}")
                        .first()
                    )
                    if not existing_txn:
                        transaction = Transaction(
                            user_id=order.buyer.user_id,
                            seller_id=order.items[0].seller_id if order.items else None,
                            amount=payment.amount,
                            type="debit",
                            reference=f"PAY_{payment.id}",
                            status="completed",
                            payment_metadata=gateway_response or {},
                        )
                        session.add(transaction)

            session.flush()

            if not already_completed:
                PaymentService._send_payment_notifications(
                    payment, PaymentStatus.COMPLETED
                )
                PaymentService._emit_payment_confirmed(payment)

            PaymentService._invalidate_payment_cache(payment.id)
            return True

    @staticmethod
    def _emit_payment_confirmed(payment: Payment):
        try:
            from app.realtime.event_manager import EventManager

            EventManager.emit_to_order(
                payment.order_id,
                "payment_confirmed",
                {
                    "payment_id": payment.id,
                    "order_id": payment.order_id,
                    "user_id": (
                        payment.order.buyer.user_id
                        if payment.order and payment.order.buyer
                        else None
                    ),
                    "amount": payment.amount,
                    "status": payment.status.value,
                    "transaction_id": payment.transaction_id,
                    "metadata": {
                        "method": payment.method.value if payment.method else None,
                        "order_number": (
                            payment.order.order_number if payment.order else None
                        ),
                    },
                },
            )
        except Exception as e:
            logger.warning(f"Failed to queue payment_confirmed event: {e}")

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
            order = session.query(Order).options(joinedload(Order.buyer)).get(order_id)
            if not order:
                raise NotFoundError("Order not found")

            resolved_amount = PaymentService._resolve_order_payment_amount(
                order, amount
            )

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
                amount=resolved_amount,
                currency=currency,
                method=method,
                status=PaymentStatus.PENDING,
                gateway_response={},
                idempotency_key=idempotency_key or str(uuid.uuid4()),
            )

            session.add(payment)
            session.flush()

            wallet_payment_id = None

            if method == PaymentMethod.WALLET:
                if not order.buyer or not order.buyer.user_id:
                    raise ValidationError("Buyer account required for wallet payment")
                from app.wallet.services import WalletService

                payment.transaction_id = f"WALLET_{payment.id}"
                WalletService.pay_for_order(
                    order.buyer.user_id,
                    order_id,
                    payment.id,
                    resolved_amount,
                    currency=currency,
                )
                payment.status = PaymentStatus.COMPLETED
                payment.paid_at = datetime.utcnow()
                wallet_payment_id = payment.id
            elif method == PaymentMethod.CARD:
                PaymentService._initialize_paystack_transaction(payment, metadata)

            PaymentService._cache_payment(payment)

            if wallet_payment_id:
                session.flush()

        if wallet_payment_id:
            PaymentService.complete_payment(payment_id=wallet_payment_id)
            return PaymentService.get_payment(wallet_payment_id)

        return payment

    @staticmethod
    def process_payment(payment_id: str, payment_data: Dict[str, Any]) -> Payment:
        """Process payment with Paystack"""
        resolved_id = payment_id
        gateway_response: Dict[str, Any] = {}
        result_status: Optional[PaymentStatus] = None

        with session_scope() as session:
            payment = session.query(Payment).get(payment_id)
            if not payment:
                raise NotFoundError("Payment not found")

            if payment.status != PaymentStatus.PENDING:
                raise ValidationError("Payment is not in pending status")

            try:
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

                payment.status = result["status"]
                if result.get("transaction_id"):
                    payment.transaction_id = result["transaction_id"]
                payment.gateway_response = result.get("gateway_response", {})
                result_status = result["status"]
                gateway_response = payment.gateway_response
                resolved_id = payment.id

                if result["status"] == PaymentStatus.COMPLETED:
                    payment.paid_at = datetime.utcnow()
                elif result["status"] == PaymentStatus.FAILED:
                    PaymentService._send_payment_notifications(
                        payment, PaymentStatus.FAILED
                    )

                session.flush()

            except Exception as e:
                logger.error(f"Payment processing failed: {str(e)}")
                payment.status = PaymentStatus.FAILED
                payment.gateway_response = {"error": str(e)}
                session.flush()
                PaymentService._send_payment_notifications(
                    payment, PaymentStatus.FAILED
                )
                raise APIError("Payment processing failed", 500)

        if result_status == PaymentStatus.COMPLETED:
            PaymentService.complete_payment(
                payment_id=resolved_id,
                gateway_response=gateway_response,
            )

        return PaymentService.get_payment(resolved_id)

    @staticmethod
    def verify_payment(payment_id: str) -> Dict[str, Any]:
        """Verify payment status with Paystack and persist success when confirmed."""
        with session_scope() as session:
            payment = session.query(Payment).get(payment_id)
            if not payment:
                raise NotFoundError("Payment not found")

            if payment.status == PaymentStatus.COMPLETED:
                return {
                    "verified": True,
                    "amount": payment.amount,
                    "gateway_response": payment.gateway_response,
                    "already_completed": True,
                }

            if not payment.transaction_id:
                raise ValidationError("No transaction ID to verify")

            transaction_id = payment.transaction_id

        try:
            response = requests.get(
                f"{PaymentService.PAYSTACK_BASE_URL}/transaction/verify/{transaction_id}",
                headers={
                    "Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"
                },
                timeout=20,
            )

            if response.status_code == 200:
                data = response.json()
                if data["status"] and data["data"]["status"] == "success":
                    # The gateway confirmed the charge — from here on the user
                    # must see success. Local completion (inventory, ledger,
                    # notifications) can fail transiently (e.g. losing the race
                    # with the webhook); log it and let the webhook/verify
                    # retry reconcile instead of telling a paid user "failed".
                    try:
                        PaymentService.complete_payment(
                            payment_id=payment_id,
                            gateway_response=data,
                        )
                    except Exception:
                        logger.exception(
                            "Local completion failed after gateway-confirmed "
                            "success (payment %s); webhook will reconcile",
                            payment_id,
                        )
                    return {
                        "verified": True,
                        "amount": data["data"]["amount"] / 100,
                        "gateway_response": data,
                    }
                return {"verified": False, "gateway_response": data}
            raise APIError("Failed to verify payment with gateway", 500)

        except APIError:
            raise
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
    def handle_webhook(
        payload: Dict[str, Any],
        signature: str,
        raw_body: Optional[bytes] = None,
    ) -> bool:
        """Handle Paystack webhook"""
        try:
            if not PaymentService._verify_webhook_signature(signature, raw_body):
                logger.warning("Invalid webhook signature")
                return False

            event = payload.get("event")
            data = payload.get("data", {})

            if event == "charge.success":
                return PaymentService._handle_successful_charge(data)
            elif event == "transfer.success":
                return PaymentService._handle_successful_transfer(data)
            elif event == "transfer.failed":
                return PaymentService._handle_failed_transfer(data)
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
    def _resolve_subaccount_split(order: Order) -> Optional[Dict[str, str]]:
        """Return Paystack subaccount code when order has a single registered seller."""
        seller_ids = {item.seller_id for item in order.items if item.seller_id}
        if len(seller_ids) != 1:
            return None

        seller_id = next(iter(seller_ids))
        seller = (
            order.items[0].seller
            if order.items and order.items[0].seller_id == seller_id
            else None
        )
        if not seller:
            with session_scope() as session:
                seller = session.query(Seller).get(seller_id)
        if not seller or not seller.paystack_subaccount_code:
            return None

        return {"subaccount_code": seller.paystack_subaccount_code}

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

            # Carry the originating platform through Paystack's redirect so the
            # final callback knows whether to send the user back to the mobile
            # app (deep link) or the web app.
            platform = (metadata or {}).get("platform", "web")
            callback_url = (
                f"{base_url}/api/v1/payments/callback/{payment.id}"
                f"?platform={platform}"
            )

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

            split = PaymentService._resolve_subaccount_split(order)
            if split:
                payload["subaccount"] = split["subaccount_code"]
                order.paystack_split_used = True

            response = requests.post(
                f"{PaymentService.PAYSTACK_BASE_URL}/transaction/initialize",
                json=payload,
                headers={
                    "Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"
                },
                timeout=20,
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
                timeout=20,
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
                timeout=20,
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
    def _verify_webhook_signature(signature: str, raw_body: Optional[bytes]) -> bool:
        """Verify Paystack webhook signature against the raw request body."""
        if not signature or not raw_body:
            return False
        try:
            computed_signature = hmac.new(
                PaymentService.PAYSTACK_SECRET_KEY.encode("utf-8"),
                raw_body,
                hashlib.sha512,
            ).hexdigest()
            return hmac.compare_digest(computed_signature, signature)
        except Exception:
            return False

    @staticmethod
    def _handle_successful_charge(data: Dict[str, Any]) -> bool:
        """Handle successful charge webhook"""
        reference = data.get("reference")
        if not reference:
            return False

        metadata = data.get("metadata") or {}
        if reference.startswith("TOP_") or metadata.get("type") == "wallet_topup":
            from app.wallet.services import WalletService

            return WalletService.complete_topup(reference, data)

        return PaymentService.complete_payment(
            reference=reference,
            gateway_response=data,
        )

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
        """Handle successful transfer webhook (wallet withdrawals)."""
        from app.wallet.services import WalletService

        reference = data.get("reference") or data.get("transfer_code")
        if not reference:
            return False
        return WalletService.complete_withdrawal_transfer(reference)

    @staticmethod
    def _handle_failed_transfer(data: Dict[str, Any]) -> bool:
        """Handle failed transfer webhook and refund wallet."""
        from app.wallet.services import WalletService

        reference = data.get("reference") or data.get("transfer_code")
        if not reference:
            return False
        reason = data.get("reason") or "Paystack transfer failed"
        return WalletService.fail_withdrawal_transfer(reference, reason)

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
                "created_at": (
                    payment.created_at.isoformat() if payment.created_at else None
                ),
                "updated_at": (
                    payment.updated_at.isoformat() if payment.updated_at else None
                ),
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
