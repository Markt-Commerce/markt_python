# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, current_user


bp = Blueprint("cart", __name__, description="Cart operations", url_prefix="/cart")

# TODOs:
@bp.route("/")
class CartManagement(MethodView):
    # TODO: Add item to cart with variants
    # TODO: Update cart item quantities
    # TODO: Apply promo codes
    # TODO: Cart abandonment recovery
    def get(self):
        pass


@bp.route("/checkout")
class CheckoutProcess(MethodView):
    # TODO: Initiate checkout
    # TODO: Validate cart contents
    # TODO: Shipping options
    # TODO: Payment method selection
    def post(self):
        pass
