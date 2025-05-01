# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, current_user

# app imports
from .schemas import ChatSchema, OfferSchema

bp = Blueprint("chats", __name__, description="Chat operations", url_prefix="/chats")


# Commerce Chat
# -----------------------------------------------
@bp.route("/product/<product_id>")
class ProductChat(MethodView):
    @login_required
    @bp.response(201, ChatSchema)
    def post(self, product_id):
        """Start chat about a product"""
        # TODO: Connect buyer to seller
        # TODO: Product context in chat
        # TODO: Offer negotiation


@bp.route("/<chat_id>/offer")
class MakeOffer(MethodView):
    @login_required
    @bp.response(201, OfferSchema)
    def post(self, chat_id):
        """Make price offer in chat"""
        # TODO: Price negotiation
        # TODO: Offer expiration
        # TODO: Counter offers


# -----------------------------------------------
