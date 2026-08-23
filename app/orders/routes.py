# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user
from flask import jsonify, make_response

# project imports
from app.libs.schemas import PaginationQueryArgs
from app.libs.decorators import seller_required, buyer_required
from app.libs.errors import APIError
from app.payments.schemas import PaymentSchema

# app imports
from .services import OrderService, SellerOrderService
from .schemas import (
    OrderSchema,
    OrderCreateSchema,
    TrackingSchema,
    ReviewSchema,
    OrderItemSchema,
    OrderPaginationSchema,
    SellerOrderResponseSchema,
    BuyerOrderSchema,
    OrderItemStatusUpdateSchema,
    OrderCancelSchema,
    OrderCancelResponseSchema,
    OrderReturnRequestSchema,
    OrderReturnResponseSchema,
    OrderReturnActionSchema,
    OrderEventSchema,
    DeliveryWaitChoiceSchema,
    DeliveryWaitChoiceResponseSchema,
)

bp = Blueprint("orders", __name__, description="Order operations", url_prefix="/orders")


@bp.route("/")
class OrderList(MethodView):
    @login_required
    @buyer_required
    @bp.response(200, BuyerOrderSchema(many=True))
    def get(self):
        """List user's orders"""
        return OrderService.get_user_orders(current_user.buyer_account.id)

    @login_required
    @buyer_required
    @bp.arguments(OrderCreateSchema)
    def post(self, order_data):
        """Create new order from cart (deprecated — use POST /cart/checkout)."""
        response = make_response(
            jsonify(
                {
                    "message": (
                        "POST /orders is deprecated. "
                        "Use POST /cart/checkout to create an order from the active cart."
                    ),
                    "replacement": "/api/v1/cart/checkout",
                }
            ),
            410,
        )
        response.headers["Deprecation"] = "true"
        response.headers["Link"] = '</api/v1/cart/checkout>; rel="successor-version"'
        return response


@bp.route("/<order_id>/pay")
class OrderPayment(MethodView):
    @login_required
    @bp.arguments(PaymentSchema)
    @bp.response(200, OrderSchema)
    def post(self, payment_data, order_id):
        """Process payment for order"""
        return OrderService.process_payment(order_id, payment_data)


@bp.route("/<string:order_id>")
class OrderDetail(MethodView):
    @login_required
    @bp.response(200, OrderSchema)
    def get(self, order_id):
        """Get order details (buyer who placed it, or a seller with items in it)"""
        order = OrderService.get_order(order_id)
        if not order:
            abort(404, message="Order not found")

        is_buyer_owner = bool(
            current_user.buyer_account
            and order.buyer_id == current_user.buyer_account.id
        )
        is_involved_seller = bool(
            current_user.seller_account
            and any(
                item.seller_id == current_user.seller_account.id for item in order.items
            )
        )
        if not (is_buyer_owner or is_involved_seller):
            # 404 (not 403) so order ids can't be probed for existence
            abort(404, message="Order not found")
        return order


@bp.route("/<string:order_id>/events")
class OrderEventList(MethodView):
    @login_required
    @buyer_required
    @bp.response(200, OrderEventSchema(many=True))
    def get(self, order_id):
        """14.2/15: buyer-facing fulfilment history for one order --
        who fulfilled each item, and why a substitution happened."""
        try:
            return OrderService.get_order_events(
                order_id, current_user.buyer_account.id
            )
        except APIError as e:
            message = getattr(e, "message", str(e))
            status_code = getattr(e, "status_code", 400)
            abort(status_code, message=message)


@bp.route("/seller")
class SellerOrderList(MethodView):
    @login_required
    @seller_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, SellerOrderResponseSchema)
    def get(self, args):
        """List orders for current seller"""
        return SellerOrderService.get_seller_orders(
            current_user.seller_account.id,
            status=args.get("status"),
            page=args.get("page", 1),
            per_page=args.get("per_page", 20),
        )


@bp.route("/seller/stats")
class SellerOrderStats(MethodView):
    @login_required
    @seller_required
    @bp.response(200)
    def get(self):
        """Get seller order statistics"""
        return SellerOrderService.get_seller_order_stats(current_user.seller_account.id)


@bp.route("/seller/items/<int:order_item_id>")
class SellerOrderItem(MethodView):
    @login_required
    @seller_required
    @bp.arguments(OrderItemStatusUpdateSchema)
    @bp.response(200, OrderItemSchema)
    def patch(self, status_data, order_item_id):
        """Update order item status"""
        if not current_user.seller_account and not current_user.is_seller:
            abort(403, message="Only sellers can access this endpoint")

        return SellerOrderService.update_order_item_status(
            order_item_id, status_data["status"], current_user.seller_account.id
        )


# Order Enhancements
# -----------------------------------------------
@bp.route("/<order_id>/track")
class TrackOrder(MethodView):
    @login_required
    @bp.response(200, TrackingSchema)
    def get(self, order_id):
        """Track order status and delivery progress"""
        try:
            return OrderService.track_order(order_id, current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/<order_id>/cancel")
class CancelOrder(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(OrderCancelSchema)
    @bp.response(200, OrderCancelResponseSchema)
    def post(self, cancel_data, order_id):
        """Cancel an order (buyer only, before shipment)"""
        try:
            order = OrderService.cancel_order(
                order_id,
                current_user.buyer_account.id,
                reason=cancel_data.get("reason"),
            )
            from app.payments.models import PaymentStatus

            refund_amount = 0.0
            for payment in order.payments or []:
                if payment.status == PaymentStatus.REFUNDED:
                    refund_amount = payment.amount
                    break
            return {
                "order_id": order.id,
                "status": order.status.value,
                "cancelled_at": order.cancelled_at,
                "cancel_reason": order.cancel_reason,
                "refund_amount": refund_amount,
            }
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/<order_id>/delivery-wait-choice")
class OrderDeliveryWaitChoice(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(DeliveryWaitChoiceSchema)
    @bp.response(200, DeliveryWaitChoiceResponseSchema)
    def post(self, choice_data, order_id):
        """10.3: buyer responds to the thin-volume delivery prompt --
        wait for a fuller run (optionally consenting to the single-drop
        fallback rate) or pay now for single/near-single delivery."""
        from app.deliveries.models import DeliveryRunWaitChoice
        from app.deliveries.runs import DeliveryRunService

        try:
            run_order = DeliveryRunService.set_wait_choice(
                order_id,
                current_user.buyer_account.id,
                DeliveryRunWaitChoice(choice_data["choice"]),
                fallback_consent=choice_data.get("fallback_consent", False),
            )
            return {
                "order_id": run_order.order_id,
                "choice": run_order.wait_choice.value,
                "fallback_consent": run_order.fallback_consent,
            }
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/<order_id>/returns")
class OrderReturnRequest(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(OrderReturnRequestSchema)
    @bp.response(201, OrderReturnResponseSchema)
    def post(self, return_data, order_id):
        """Request a return for a shipped or delivered order"""
        try:
            return OrderService.request_return(
                order_id,
                current_user.buyer_account.id,
                reason=return_data["reason"],
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/returns/<return_id>/approve")
class ApproveOrderReturn(MethodView):
    @login_required
    @seller_required
    @bp.arguments(OrderReturnActionSchema)
    @bp.response(200, OrderReturnResponseSchema)
    def post(self, action_data, return_id):
        """Approve a buyer return request and refund to wallet"""
        try:
            return OrderService.approve_return(
                return_id,
                current_user.seller_account.id,
                seller_notes=action_data.get("seller_notes"),
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/returns/<return_id>/reject")
class RejectOrderReturn(MethodView):
    @login_required
    @seller_required
    @bp.arguments(OrderReturnActionSchema)
    @bp.response(200, OrderReturnResponseSchema)
    def post(self, action_data, return_id):
        """Reject a buyer return request"""
        try:
            return OrderService.reject_return(
                return_id,
                current_user.seller_account.id,
                seller_notes=action_data.get("seller_notes"),
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/<order_id>/review")
class OrderReview(MethodView):
    @login_required
    @bp.response(201, ReviewSchema)
    def post(self, order_id):
        """Submit order review"""
        # TODO: Product ratings
        # TODO: Seller ratings
        # TODO: Photo reviews


# -----------------------------------------------
