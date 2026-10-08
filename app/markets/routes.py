from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import current_user

from app.libs.schemas import PaginationQueryArgs
from app.libs.errors import NotFoundError
from app.products.schemas import ProductSearchResultSchema
from app.socials.schemas import PostDetailSearchResultSchema

from .services import MarketService
from .schemas import MarketSchema, MarketListSchema

bp = Blueprint(
    "markets", __name__, description="Market browsing operations", url_prefix="/markets"
)


@bp.route("/")
class MarketList(MethodView):
    @bp.response(200, MarketListSchema)
    def get(self):
        """List active markets (13: click a market to browse it)"""
        return {"markets": MarketService.list_markets()}


@bp.route("/<int:market_id>")
class MarketDetail(MethodView):
    @bp.response(200, MarketSchema)
    def get(self, market_id):
        """Get a single market"""
        try:
            return MarketService.get_market(market_id)
        except NotFoundError as e:
            abort(404, message=str(e))


@bp.route("/<int:market_id>/sellers")
class MarketSellers(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, description="Sellers assigned to this market")
    def get(self, args, market_id):
        """List sellers in a market"""
        try:
            user_id = current_user.id if current_user.is_authenticated else None
            return MarketService.list_market_sellers(market_id, args, user_id=user_id)
        except NotFoundError as e:
            abort(404, message=str(e))


@bp.route("/<int:market_id>/products")
class MarketProducts(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, ProductSearchResultSchema)
    def get(self, args, market_id):
        """List products from sellers in a market"""
        try:
            return MarketService.list_market_products(market_id, args)
        except NotFoundError as e:
            abort(404, message=str(e))


@bp.route("/<int:market_id>/posts")
class MarketPosts(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, PostDetailSearchResultSchema)
    def get(self, args, market_id):
        """List posts from sellers in a market"""
        try:
            return MarketService.list_market_posts(market_id, args)
        except NotFoundError as e:
            abort(404, message=str(e))
