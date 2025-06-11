# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user
from flask import request

# project imports
from app.socials.schemas import ShareSchema, CommentSchema
from app.libs.decorators import seller_required, buyer_required
from app.libs.schemas import PaginationQueryArgs
from app.socials.services import ProductSocialService
from app.socials.schemas import (
    ProductLikeSchema,
    ProductCommentSchema,
    ProductCommentsSchema,
)

# app imports
from .services import ProductService
from .schemas import (
    ProductSchema,
    ProductCreateSchema,
    ProductUpdateSchema,
    ProductSearchSchema,
    ProductSearchResultSchema,
    BulkProductResultSchema,
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
    @seller_required
    @bp.arguments(ProductCreateSchema)
    @bp.response(201, ProductSchema)
    def post(self, product_data):
        """Create new product (for sellers)"""
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


@bp.route("/bulk")
class ProductBulkCreate(MethodView):
    @login_required
    @seller_required
    @bp.arguments(ProductCreateSchema(many=True))
    @bp.response(201, BulkProductResultSchema)
    def post(self, products_data):
        """Bulk create products (for sellers)"""
        # if not current_user.seller_account:
        #     raise ForbiddenError("Only sellers can create products")
        return ProductService.bulk_create_products(
            products_data, current_user.seller_account.id
        )


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


@bp.route("/<product_id>/like")
class ProductLike(MethodView):
    @login_required
    @bp.response(201, ProductLikeSchema)
    def post(self, product_id):
        """Like a product"""
        return ProductSocialService.like_product(current_user.id, product_id)


@bp.route("/<product_id>/comments")
class ProductComments(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, ProductCommentsSchema)
    def get(self, args, product_id):
        """Get product comments"""
        return ProductSocialService.get_product_comments(
            product_id, page=args.get("page", 1), per_page=args.get("per_page", 20)
        )

    @login_required
    @bp.arguments(ProductCommentSchema)
    @bp.response(201, ProductCommentSchema)
    def post(self, comment_data, product_id):
        """Add comment to product"""
        return ProductSocialService.add_product_comment(
            current_user.id,
            product_id,
            comment_data["content"],
            comment_data.get("parent_id"),
        )


@bp.route("/<product_id>/view")
class ProductView(MethodView):
    @bp.response(204)
    def post(self, product_id):
        """Track product view"""
        ProductSocialService.track_product_view(
            product_id,
            current_user.id if current_user.is_authenticated else None,
            request.remote_addr,
        )
        return "", 204


@bp.route("/<product_id>/share")
class ShareProduct(MethodView):
    @login_required
    @bp.response(200, ShareSchema)
    def post(self, product_id):
        """Share product socially"""
        # TODO: Generate share links
        # TODO: Track shares
        # TODO: Reward system for shares


# -----------------------------------------------

# TODO: Add more endpoints for:
# - Product reviews
# - Product questions
# - Bulk product operations
# - Export/import products
