# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, current_user

# app imports
from .schemas import RequestSchema

bp = Blueprint(
    "requests", __name__, description="Buyer Request operations", url_prefix="/requests"
)


# Buyer Requests
# -----------------------------------------------
@bp.route("/<request_id>/upvote")
class UpvoteRequest(MethodView):
    @login_required
    @bp.response(200, RequestSchema)
    def post(self, request_id):
        """Upvote a buyer request"""
        # TODO: Track upvotes
        # TODO: Popular requests ranking
        # TODO: Prevent duplicate upvotes


@bp.route("/trending-requests")
class TrendingRequests(MethodView):
    @bp.response(200, RequestSchema(many=True))
    def get(self):
        """Get trending requests"""
        # TODO: Algorithm based on upvotes, comments
        # TODO: Time-bound trending window


# -----------------------------------------------
