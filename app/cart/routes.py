# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user

# project imports
from app.libs.decorators import buyer_required
from app.libs.errors import APIError

# app imports
from .services import CartService
from .schemas import (
    CartSchema,
    CartItemSchema,
    AddToCartSchema,
    UpdateCartItemSchema,
    CheckoutSchema,
    CartSummarySchema,
)


bp = Blueprint(
    "cart", __name__, description="Shopping cart operations", url_prefix="/cart"
)


@bp.route("/")
class CartDetail(MethodView):
    @login_required
    @buyer_required
    @bp.response(200, CartSchema)
    def get(self):
        """Get current user's cart"""
        try:
            return CartService.get_cart(current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @buyer_required
    @bp.response(204)
    def delete(self):
        """Clear cart"""
        try:
            CartService.clear_cart(current_user.id)
            return None
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/add")
class AddToCart(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(AddToCartSchema)
    @bp.response(201, CartItemSchema)
    def post(self, item_data):
        """Add item to cart"""
        try:
            return CartService.add_to_cart(
                current_user.id,
                item_data["product_id"],
                item_data.get("quantity", 1),
                item_data.get("variant_id"),
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/items/<int:item_id>")
class CartItemDetail(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(UpdateCartItemSchema)
    @bp.response(200, CartItemSchema)
    def put(self, update_data, item_id):
        """Update cart item quantity"""
        try:
            return CartService.update_cart_item(
                current_user.id, item_id, update_data["quantity"]
            )
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @buyer_required
    @bp.response(204)
    def delete(self, item_id):
        """Remove item from cart"""
        try:
            CartService.remove_from_cart(current_user.id, item_id)
            return None
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/checkout")
class Checkout(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(CheckoutSchema)
    @bp.response(201)
    def post(self, checkout_data):
        """Checkout cart and create order"""
        try:
            order = CartService.checkout_cart(current_user.id, checkout_data)
            return {"order_id": order.id, "message": "Order created successfully"}
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/summary")
class CartSummary(MethodView):
    @login_required
    @buyer_required
    @bp.response(200, CartSummarySchema)
    def get(self):
        """Get cart summary"""
        try:
            return CartService.get_cart_summary(current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/coupon")
class ApplyCoupon(MethodView):
    @login_required
    @buyer_required
    @bp.response(200)
    def post(self):
        """Apply coupon code to cart"""
        try:
            # TODO: Get coupon code from request body
            coupon_code = "SAMPLE10"  # Placeholder
            return CartService.apply_coupon(current_user.id, coupon_code)
        except APIError as e:
            abort(e.status_code, message=e.message)
