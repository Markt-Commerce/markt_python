# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required

# project imports
from app.socials.schemas import ShareSchema, CommentSchema

# app imports
from .services import ProductService
from .schemas import ProductSchema, ProductCreateSchema, ProductUpdateSchema

bp = Blueprint(
    "products", __name__, description="Product operations", url_prefix="/products"
)


@bp.route("/")
class ProductList(MethodView):
    @bp.response(200, ProductSchema(many=True))
    def get(self):
        """List all products"""
        return ProductService.get_all_products()

    @bp.arguments(ProductCreateSchema)
    @bp.response(201, ProductSchema)
    def post(self, product_data):
        """Create new product"""
        return ProductService.create_product(product_data)


@bp.route("/<int:product_id>")
class ProductDetail(MethodView):
    @bp.response(200, ProductSchema)
    def get(self, product_id):
        """Get product details"""
        return ProductService.get_product(product_id)

    @bp.arguments(ProductUpdateSchema)
    @bp.response(200, ProductSchema)
    def put(self, product_data, product_id):
        """Update product"""
        return ProductService.update_product(product_id, product_data)

    @bp.response(204)
    def delete(self, product_id):
        """Delete product"""
        ProductService.delete_product(product_id)
        return None


# Product Discovery
# -----------------------------------------------
@bp.route("/search")
class ProductSearch(MethodView):
    @bp.response(200, ProductSchema(many=True))
    def get(self):
        """Search products with filters"""
        # TODO: Full-text search
        # TODO: Filter by price, category, ratings
        # TODO: Sort options (newest, popular, price)


@bp.route("/trending")
class TrendingProducts(MethodView):
    @bp.response(200, ProductSchema(many=True))
    def get(self):
        """Get trending products"""
        # TODO: Algorithm based on views, purchases, likes
        # TODO: Time-bound trending window


# -----------------------------------------------

# Social Commerce Features
# -----------------------------------------------
@bp.route("/<product_id>/like")
class LikeProduct(MethodView):
    @login_required
    @bp.response(204)
    def post(self, product_id):
        """Like a product"""
        # TODO: Track likes
        # TODO: Add to user's favorites
        # TODO: Notification to seller


@bp.route("/<product_id>/share")
class ShareProduct(MethodView):
    @login_required
    @bp.response(200, ShareSchema)
    def post(self, product_id):
        """Share product socially"""
        # TODO: Generate share links
        # TODO: Track shares
        # TODO: Reward system for shares


@bp.route("/<product_id>/comments")
class ProductComments(MethodView):
    @bp.response(200, CommentSchema(many=True))
    def get(self, product_id):
        """Get product comments"""
        # TODO: Paginated comments
        # TODO: Nested replies
        # TODO: Sorting options


# -----------------------------------------------
