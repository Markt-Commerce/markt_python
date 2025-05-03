# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, current_user

# app imports
from .services import CartService
from .schemas import CartSchema, AddToCartSchema

bp = Blueprint("cart", __name__, description="Cart operations", url_prefix="/cart")


@bp.route("/")
class CartManagement(MethodView):
    @login_required
    @bp.response(200, CartSchema)
    def get(self):
        """Get user's cart"""
        return CartService.get_user_cart(current_user.buyer_account.id)

    @login_required
    @bp.arguments(AddToCartSchema)
    @bp.response(200, CartSchema)
    def post(self, item_data):
        """Add item to cart"""
        return CartService.add_to_cart(
            current_user.buyer_account.id,
            item_data["product_id"],
            item_data.get("quantity", 1),
            item_data.get("variant_id"),
        )


@bp.route("/checkout")
class CheckoutInitiation(MethodView):
    @login_required
    @bp.response(200)
    def post(self):
        """Initiate checkout process"""
        # TODO: Validate cart
        # TODO: Create order draft
        # TODO: Return payment options
