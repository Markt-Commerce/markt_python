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
        )


@bp.route("/<payment_id>/process")
class PaymentProcess(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(PaymentSchema)
    @bp.response(200, PaymentSchema)
    def post(self, payment_data, payment_id):
        """Process payment with Paystack"""
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
            )

            # Return Paystack initialization data
            if payment.gateway_response and "data" in payment.gateway_response:
                return {
                    "payment_id": payment.id,
                    "authorization_url": payment.gateway_response["data"][
                        "authorization_url"
                    ],
                    "reference": payment.gateway_response["data"]["reference"],
                    "access_code": payment.gateway_response["data"]["access_code"],
                }
            else:
                raise APIError("Failed to initialize payment", 500)

        except Exception as e:
            abort(500, message=str(e))


@bp.route("/callback/<payment_id>")
class PaymentCallback(MethodView):
    def get(self, payment_id):
        """Handle payment callback from Paystack"""
        try:
            # Get reference from query params
            reference = request.args.get("reference")
            if not reference:
                abort(400, message="Missing reference")

            # Verify payment
            verification_result = PaymentService.verify_payment(payment_id)

            if verification_result["verified"]:
                return (
                    jsonify(
                        {
                            "status": "success",
                            "message": "Payment verified successfully",
                            "payment_id": payment_id,
                        }
                    ),
                    200,
                )
            else:
                return (
                    jsonify(
                        {
                            "status": "failed",
                            "message": "Payment verification failed",
                            "payment_id": payment_id,
                        }
                    ),
                    400,
                )

        except Exception as e:
            abort(500, message=str(e))


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
