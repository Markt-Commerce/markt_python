# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, current_user

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
        """Create new order"""
        return OrderService.create_order(order_data)


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
