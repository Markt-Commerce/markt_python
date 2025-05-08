# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user

# project imports
from app.libs.schemas import PaginationQueryArgs
from app.libs.decorators import seller_required, buyer_required
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
    @bp.arguments(OrderCreateSchema)
    @bp.response(201, OrderSchema)
    def post(self, order_data):
        """Create new order from cart"""
        return OrderService.create_order(
            order_data["cart_id"],
            current_user.buyer_account.id,
            order_data["shipping_address"],
            order_data.get("payment_method", "card"),
        )


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
        """Get order details"""
        return OrderService.get_order(order_id)


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
    @bp.response(200, OrderItemSchema)
    def patch(self, order_item_id, status_data):
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
        """Track order status"""
        # TODO: Real-time shipping updates
        # TODO: Delivery estimation
        # TODO: Map integration


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
