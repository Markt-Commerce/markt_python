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
        return PaymentService.create_payment(
            order_id=payment_data["order_id"],
            amount=payment_data["amount"],
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
            payload = request.get_json()
            if not payload:
                abort(400, message="Invalid webhook payload")

            # Process webhook
            success = PaymentService.handle_webhook(payload, signature)

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
            payment = PaymentService.create_payment(
                order_id=payment_data["order_id"],
                amount=payment_data["amount"],
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


@bp.route("/callback/<payment_id>")
class PaymentCallback(MethodView):
    def get(self, payment_id):
        """Handle payment callback from Paystack and redirect to frontend"""
        from flask import redirect
        from main.config import settings

        try:
            # Get reference from query params
            reference = request.args.get("reference")
            if not reference:
                # Redirect to frontend error page
                frontend_url = settings.FRONTEND_BASE_URL or "http://localhost:3000"
                return redirect(
                    f"{frontend_url}/payment/failed?error=missing_reference"
                )

            # Verify payment
            verification_result = PaymentService.verify_payment(payment_id)

            # Get frontend URL from config
            frontend_url = settings.FRONTEND_BASE_URL or "http://localhost:3000"

            if verification_result["verified"]:
                # Redirect to frontend success page
                return redirect(
                    f"{frontend_url}/payment/success?payment_id={payment_id}&reference={reference}"
                )
            else:
                # Redirect to frontend failure page
                return redirect(
                    f"{frontend_url}/payment/failed?payment_id={payment_id}&reference={reference}"
                )

        except Exception as e:
            current_app.logger.error(f"Payment callback error: {str(e)}")
            # Redirect to frontend error page
            frontend_url = settings.FRONTEND_BASE_URL or "http://localhost:3000"
            return redirect(f"{frontend_url}/payment/failed?error=server_error")


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
