# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, current_user

# project imports
from app.payments.schemas import PaymentSchema

# app imports
from .services import OrderService
from .schemas import OrderSchema, OrderCreateSchema, TrackingSchema, ReviewSchema

bp = Blueprint("orders", __name__, description="Order operations", url_prefix="/orders")


@bp.route("/")
class OrderList(MethodView):
    @login_required
    @bp.response(200, OrderSchema(many=True))
    def get(self):
        """List user's orders"""
        return OrderService.get_user_orders(current_user.id)

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


@bp.route("/<int:order_id>")
class OrderDetail(MethodView):
    @login_required
    @bp.response(200, OrderSchema)
    def get(self, order_id):
        """Get order details"""
        return OrderService.get_order(order_id)


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
