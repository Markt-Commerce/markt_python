import logging

from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import current_user

from app.libs.schemas import PaginationQueryArgs
from app.products.services import ProductService
from app.socials.services import PostService
from app.users.services import ShopService

from app.products.schemas import ProductSchema
from app.socials.schemas import PostDetailSchema
from app.users.schemas import SellerSimpleSchema

from marshmallow import Schema, fields

logger = logging.getLogger(__name__)


bp = Blueprint(
    "search",
    __name__,
    description="Unified search across products, posts and sellers",
    url_prefix="/search",
)


class GlobalSearchResultSchema(Schema):
    """Response schema for the unified search endpoint.

    The shape is intentionally simple for the frontend:
    {
      "page": 1,
      "per_page": 20,
      "products": [...],
      "posts": [...],
      "sellers": [...]
    }
    """

    page = fields.Int(required=True)
    per_page = fields.Int(required=True)

    products = fields.List(fields.Nested(ProductSchema), required=True)
    posts = fields.List(fields.Nested(PostDetailSchema), required=True)
    sellers = fields.List(fields.Nested(SellerSimpleSchema), required=True)


@bp.route("/")
class GlobalSearch(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, GlobalSearchResultSchema)
    def get(self, args):
        """
        Unified search endpoint.

        - Uses the same `page`, `per_page` and `search` query params as the
          existing list/search endpoints.
        - Returns a single object with `products`, `posts`, `sellers` and
          the current page so the frontend does not have to stitch together
          multiple responses.
        """
        page = args.get("page", 1)
        per_page = args.get("per_page", 20)
        search_term = args.get("search")

        # If no search term is supplied, we still return empty lists so the
        # frontend has a predictable shape.
        if not search_term:
            return {
                "page": page,
                "per_page": per_page,
                "products": [],
                "posts": [],
                "sellers": [],
            }

        # Prepare a minimal args dict for each service. We intentionally keep
        # filters aligned so pagination feels coherent across sections.
        product_args = {"page": page, "per_page": per_page, "search": search_term}
        post_args = {"page": page, "per_page": per_page, "search": search_term}

        # Shops/sellers reuse the existing shop search service.
        shop_args = {
            "page": page,
            "per_page": per_page,
            "search": search_term,
            "active_only": True,
        }

        user_id = current_user.id if current_user.is_authenticated else None

        # Delegate to existing, battle‑tested services so we don't duplicate
        # SQL logic here.
        product_result = ProductService.search_products(product_args)
        post_result = PostService.get_posts(post_args)
        shop_result = ShopService.search_shops(shop_args, user_id)

        # Normalise to simple lists for the unified response.
        products = product_result.get("items", []) if isinstance(product_result, dict) else product_result  # type: ignore
        posts = post_result.get("items", []) if isinstance(post_result, dict) else post_result  # type: ignore
        sellers = shop_result.get("shops", [])

        return {
            "page": page,
            "per_page": per_page,
            "products": products,
            "posts": posts,
            "sellers": sellers,
        }
