from flask_smorest import Blueprint
from flask.views import MethodView
from flask import abort
from flask_login import login_required
from app.models.order_model import Order
from app.models.user_model import User
from app.models.seller_model import Seller
from app.models.buyer_model import Buyer
from app.models.product_model import Product

from ..models import User, Order, Seller, Buyer, Product, ImageNameStore
from ..utils import (
    parse_orders,
    parse_buyer_orders,
    parse_successful_orders,
    parse_unaccepted_orders,
)

from app.schemas import OrderSchema

order_bp = Blueprint(
    "Orders",
    "orders",
    description="Endpoints and routes for everything related to orders",
    url_prefix="/orders",
)


@order_bp.route("/new")
class Orders(MethodView):
    @order_bp.arguments(OrderSchema)
    @order_bp.response(201, description="order created successfully")
    def post(self, data):
        try:
            order = Order(
                buyer_id=data["buyer_id"],
                seller_id=data["seller_id"],
                product_id=data["product_id"],
                quantity=data["quantity"],
                total_price=data["total_price"],
                delivery_address=data["delivery_address"],
            )
            order.save_to_db()
            return {"message": "order created successfully."}, 201
        except Exception:
            abort(500, "could not create")


@order_bp.route("/sellers/pending/<seller_id>")
class PendingOrders(MethodView):
    @order_bp.response(200, OrderSchema)
    def get(self, seller_id):
        try:
            return [
                parse_unaccepted_orders(
                    order=order,
                    buyer=Buyer(order.buyer_id),
                    product=Product(order.product_id),
                    product_image=ImageNameStore.getproductthumbnail(order.product_id),
                )
                for order in Order.get_seller_pending_orders(seller_id)
            ]
        except Exception:
            abort(500, "could not create")


@order_bp.route("/sellers/accepted/<seller_id>")
class AcceptedOrders(MethodView):
    @order_bp.response(200, OrderSchema)
    def get(self, seller_id):
        try:
            [
                parse_unaccepted_orders(
                    order=order,
                    buyer=Buyer(order.buyer_id),
                    product=Product(order.product_id),
                    product_image=ImageNameStore.getproductthumbnail(order.product_id),
                )
                for order in Order.get_seller_accepted_orders(seller_id)
            ]
        except Exception:
            abort(500, "could not create")


@order_bp.route("/sellers/update/accept/<order_id>")
class AcceptOrders(MethodView):
    @login_required
    @order_bp.response(200, OrderSchema)
    # authentication would be needed
    def put(self, order_id):
        try:
            order = Order(order_id=order_id)
            order.accept_order()
        except Exception:
            abort(404, "order not found")


@order_bp.route("/sellers/update/decline")
class DeclineOrders(MethodView):
    @login_required
    @order_bp.response(200, OrderSchema)
    # authentication would be needed
    def put(self, order_id):
        try:
            order = Order(order_id=order_id)
            order.decline_order()
        except Exception:
            abort(404, "order not found")


@order_bp.route("/buyers/<buyer_id>")
class BuyerOrders(MethodView):
    @order_bp.response(200, OrderSchema)
    def get(self, buyer_id):
        try:
            [
                parse_buyer_orders(
                    order=order,
                    buyer=Buyer(order.buyer_id),
                    product=Product(order.product_id),
                    seller=Seller(order.seller_id),
                    product_image=ImageNameStore.getproductthumbnail(order.product_id),
                )
                for order in Order.get_buyer_orders(buyer_id)
            ]
        except Exception:
            abort(500, "could not create")


""" @order_bp.route("/buyers/update/complete")
class CompleteOrders():
  @order_bp.response(200, OrderSchema)
  def patch(self,order_id):
    try:
      order = Order(order_id=order_id)
      order.complete_order()
    except Exception as e:
      abort(404,"order not found") """
