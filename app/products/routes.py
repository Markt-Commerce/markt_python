# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user

# project imports
from app.socials.schemas import ShareSchema, CommentSchema


# app imports
from .services import ProductService
from .schemas import (
    ProductSchema,
    ProductCreateSchema,
    ProductUpdateSchema,
    ProductSearchSchema,
    ProductSearchResultSchema,
)


bp = Blueprint(
    "products", __name__, description="Product operations", url_prefix="/products"
)


@bp.route("/")
class ProductList(MethodView):
    @bp.arguments(ProductSearchSchema, location="query")
    @bp.response(200, ProductSearchResultSchema)
    def get(self, args):
        """List all products with filters"""
        return ProductService.search_products(args)

    @login_required
    @bp.arguments(ProductCreateSchema)
    @bp.response(201, ProductSchema)
    def post(self, product_data):
        """Create new product (for sellers)"""
        if not current_user.seller_account:
            abort(403, message="Only sellers can create products")
        return ProductService.create_product(
            product_data, current_user.seller_account.id
        )


@bp.route("/<product_id>")
class ProductDetail(MethodView):
    @bp.response(200, ProductSchema)
    def get(self, product_id):
        """Get product details"""
        return ProductService.get_product(product_id)

    @login_required
    @bp.arguments(ProductUpdateSchema)
    @bp.response(200, ProductSchema)
    def put(self, product_data, product_id):
        """Update product (owner only)"""
        product = ProductService.get_product(product_id)
        if product.seller_id != current_user.seller_account.id:
            abort(403, message="You can only update your own products")
        return ProductService.update_product(product_id, product_data)

    @login_required
    @bp.response(204)
    def delete(self, product_id):
        """Delete product (owner only)"""
        product = ProductService.get_product(product_id)
        if product.seller_id != current_user.seller_account.id:
            abort(403, message="You can only delete your own products")
        ProductService.delete_product(product_id)
        return None


# Product Discovery
# -----------------------------------------------
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

# TODO: Add more endpoints for:
# - Product reviews
# - Product questions
# - Bulk product operations
# - Export/import products
