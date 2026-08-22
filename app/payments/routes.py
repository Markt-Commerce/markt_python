# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user
from flask import request, jsonify, current_app

# project imports
from app.libs.schemas import PaginationQueryArgs
from app.libs.decorators import buyer_required, seller_required
from app.libs.errors import APIError

# app imports
from .services import PaymentService
from .schemas import (
    PaymentSchema,
    PaymentCreateSchema,
    PaymentVerifySchema,
    PaymentListSchema,
    PaymentProcessSchema,
    CheckoutPaymentInitializeSchema,
    CheckoutPaymentResponseSchema,
)

bp = Blueprint(
    "payments", __name__, description="Payment operations", url_prefix="/payments"
)


@bp.route("/")
class PaymentList(MethodView):
    @login_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, PaymentListSchema)
    def get(self, args):
        """List user's payments"""
        return PaymentService.list_user_payments(
            current_user.id, page=args.get("page", 1), per_page=args.get("per_page", 20)
        )


@bp.route("/create")
class PaymentCreate(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(PaymentCreateSchema)
    @bp.response(201, PaymentSchema)
    def post(self, payment_data):
        """Create a new payment"""
        # .get(): `amount` is optional in PaymentCreateSchema with no default,
        # so bracket access raised KeyError (-> 500) whenever a client omitted
        # it. The service already resolves a missing amount from order.total.
        return PaymentService.create_payment(
            order_id=payment_data["order_id"],
            amount=payment_data.get("amount"),
            currency=payment_data.get("currency", "NGN"),
            method=payment_data.get("method", "card"),
            metadata=payment_data.get("metadata"),
            idempotency_key=payment_data.get("idempotency_key"),
        )


@bp.route("/<payment_id>/process")
class PaymentProcess(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(PaymentProcessSchema)
    @bp.response(200, PaymentSchema)
    def post(self, payment_data, payment_id):
        """Process payment with Paystack.

        - For card payments, expects an `authorization_code` or `card_token`
          (see `PaymentProcessSchema`).
        - For bank transfers, expects a `bank` object which is forwarded to
          Paystack's Charge API.
        """
        return PaymentService.process_payment(payment_id, payment_data)


@bp.route("/<payment_id>/verify")
class PaymentVerify(MethodView):
    @login_required
    @bp.response(200)
    def get(self, payment_id):
        """Verify payment status with Paystack"""
        return PaymentService.verify_payment(payment_id)


@bp.route("/<payment_id>")
class PaymentDetail(MethodView):
    @login_required
    @bp.response(200, PaymentSchema)
    def get(self, payment_id):
        """Get payment details"""
        return PaymentService.get_payment(payment_id)


@bp.route("/webhook/paystack")
class PaystackWebhook(MethodView):
    def post(self):
        """Handle Paystack webhook"""
        try:
            # Get webhook signature
            signature = request.headers.get("X-Paystack-Signature")
            if not signature:
                abort(400, message="Missing webhook signature")

            # Get webhook payload
            raw_body = request.get_data()
            payload = request.get_json()
            if not payload:
                abort(400, message="Invalid webhook payload")

            # Process webhook
            success = PaymentService.handle_webhook(
                payload, signature, raw_body=raw_body
            )

            if success:
                return jsonify({"status": "success"}), 200
            else:
                return jsonify({"status": "failed"}), 400

        except Exception as e:
            # Log error but don't expose details to webhook
            current_app.logger.error(f"Webhook processing failed: {str(e)}")
            return jsonify({"status": "error"}), 500


@bp.route("/initialize")
class PaymentInitialize(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(PaymentCreateSchema)
    @bp.response(200)
    def post(self, payment_data):
        """Initialize Paystack payment (for frontend integration)"""
        try:
            # .get(): see PaymentCreate — omitting the optional `amount` must
            # not 500; the service falls back to order.total.
            payment = PaymentService.create_payment(
                order_id=payment_data["order_id"],
                amount=payment_data.get("amount"),
                currency=payment_data.get("currency", "NGN"),
                method=payment_data.get("method", "card"),
                metadata=payment_data.get("metadata"),
                idempotency_key=payment_data.get("idempotency_key"),
            )

            # Return Paystack initialization data
            # Note: gateway_response is only set for CARD payments
            # Bank transfers don't get authorization_url (they use /process endpoint)
            if payment.method.value == "card":
                if payment.gateway_response and "data" in payment.gateway_response:
                    gateway_data = payment.gateway_response["data"]
                    return {
                        "payment_id": payment.id,
                        "authorization_url": gateway_data.get("authorization_url"),
                        "reference": gateway_data.get("reference"),
                        "access_code": gateway_data.get("access_code"),
                    }
                else:
                    raise APIError(
                        "Failed to initialize payment: No gateway response from Paystack",
                        500,
                    )
            else:
                # For bank_transfer or other methods, return payment info
                # Bank transfer uses /process endpoint with bank details
                return {
                    "payment_id": payment.id,
                    "reference": payment.transaction_id or f"PAY_{payment.id}",
                    "message": "Payment created. For bank transfers, use /process endpoint with bank details.",
                }

        except APIError as e:
            current_app.logger.error(f"Payment initialization API error: {str(e)}")
            abort(e.status_code, message=e.message)
        except Exception as e:
            current_app.logger.error(
                f"Payment initialization error: {str(e)}", exc_info=True
            )
            abort(500, message=f"Failed to initialize payment: {str(e)}")


@bp.route("/checkout/initialize")
class CheckoutPaymentInitialize(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(CheckoutPaymentInitializeSchema)
    @bp.response(200, CheckoutPaymentResponseSchema)
    def post(self, checkout_data):
        """Payment-first checkout (additive alternative to POST /cart/checkout
        + POST /payments/initialize): reserves stock and starts payment
        before any Order exists. The Order is created only once payment
        succeeds -- there is no order_id in this response."""
        try:
            payment = PaymentService.initialize_checkout_payment(
                current_user.buyer_account.id,
                checkout_data,
                idempotency_key=checkout_data.get("idempotency_key"),
            )
            if payment.gateway_response and "data" in payment.gateway_response:
                gateway_data = payment.gateway_response["data"]
                breakdown = payment.pending_checkout_data or {}
                return {
                    "payment_id": payment.id,
                    "authorization_url": gateway_data.get("authorization_url"),
                    "reference": gateway_data.get("reference"),
                    "access_code": gateway_data.get("access_code"),
                    "amount": payment.amount,
                    "subtotal": breakdown.get("subtotal"),
                    "shipping_fee": breakdown.get("shipping_fee"),
                    "service_fee": breakdown.get("service_fee"),
                    "reliability_fee_opted_in": breakdown.get(
                        "reliability_fee_opted_in", False
                    ),
                    "reliability_fee_estimate": breakdown.get(
                        "reliability_fee_estimate", 0.0
                    ),
                    "capture_ceiling": breakdown.get("capture_ceiling"),
                }
            raise APIError(
                "Failed to initialize payment: No gateway response from Paystack",
                500,
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/callback/<payment_id>")
class PaymentCallback(MethodView):
    def get(self, payment_id):
        """Handle payment callback from Paystack and redirect to the mobile app or web app"""
        from flask import redirect
        from urllib.parse import urlencode
        from main.config import settings

        # The platform is set on the callback_url when the payment was
        # initialized (see PaymentService._initialize_paystack_transaction)
        # and echoed back by Paystack's redirect.
        platform = request.args.get("platform", "web")

        def client_redirect(status: str, **params):
            query_params = {k: v for k, v in params.items() if v is not None}
            query = urlencode(query_params)
            if platform == "mobile":
                url = f"{settings.MOBILE_APP_SCHEME}payment/{status}"
            else:
                url = f"{settings.WEB_APP_BASE_URL}/payment-{status}"
            return redirect(f"{url}?{query}" if query else url)

        try:
            # Get reference from query params
            reference = request.args.get("reference")
            if not reference:
                return client_redirect("failed", error="missing_reference")

            # Verify payment
            verification_result = PaymentService.verify_payment(payment_id)

            if verification_result["verified"]:
                return client_redirect(
                    "success", payment_id=payment_id, reference=reference
                )
            else:
                return client_redirect(
                    "failed", payment_id=payment_id, reference=reference
                )

        except Exception as e:
            current_app.logger.error(f"Payment callback error: {str(e)}", exc_info=True)
            # Verification can fail transiently (gateway timeout, race with the
            # charge.success webhook). If the webhook already completed this
            # payment, the money is confirmed — never show the user "failed".
            try:
                from .models import PaymentStatus

                payment = PaymentService.get_payment(payment_id)
                if payment and payment.status == PaymentStatus.COMPLETED:
                    return client_redirect(
                        "success",
                        payment_id=payment_id,
                        reference=request.args.get("reference"),
                    )
            except Exception:
                pass
            return client_redirect(
                "failed", payment_id=payment_id, error="server_error"
            )


# Admin routes for payment management
@bp.route("/admin/stats")
class PaymentStats(MethodView):
    @login_required
    @seller_required
    @bp.response(200)
    def get(self):
        """Get payment statistics (for sellers)"""
        # TODO: Implement payment statistics for sellers
        return {
            "total_payments": 0,
            "successful_payments": 0,
            "failed_payments": 0,
            "total_revenue": 0,
        }
