import logging

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
    ProductReviewSchema,
    ProductReviewsSchema,
    ReviewUpvoteSchema,
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

logger = logging.getLogger(__name__)

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
        return ProductService.create_product(product_data, current_user)


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
        return ProductService.update_product(
            product_id, current_user.seller_account.id, product_data
        )

    @login_required
    @bp.response(204)
    def delete(self, product_id):
        """Delete product (owner only)"""
        product = ProductService.get_product(product_id)
        if product.seller_id != current_user.seller_account.id:
            abort(403, message="You can only delete your own products")
        ProductService.delete_product(product_id, current_user.seller_account.id)
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


@bp.route("/trending")
class TrendingProducts(MethodView):
    # @cache.cached(timeout=300)  # 5 minute cache
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, ProductSchema(many=True))
    def get(self, args):
        """Get trending products with smart personalization"""
        return ProductService.get_trending_products(
            user_id=current_user.id if current_user.is_authenticated else None,
            limit=min(args.get("per_page", 10), 50),
        )


@bp.route("/recommended")
class RecommendedProducts(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, ProductSchema(many=True))
    def get(self, args):
        """Get personalized product recommendations"""
        user_id = current_user.id if current_user.is_authenticated else None
        limit = min(args.get("per_page", 10), 50)

        return ProductService.get_recommended_products(user_id, limit)


@bp.route("/<product_id>/reviews")
class ProductReviews(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, ProductReviewsSchema)
    def get(self, args, product_id):
        """Get product reviews"""
        return ProductSocialService.get_product_reviews(
            product_id, page=args.get("page", 1), per_page=args.get("per_page", 10)
        )

    @login_required
    @bp.arguments(ProductReviewSchema)
    @bp.response(201, ProductReviewSchema)
    def post(self, data, product_id):
        """Create product review"""
        return ProductSocialService.create_review(current_user.id, product_id, data)


@bp.route("/reviews/<review_id>/upvote")
class ReviewUpvote(MethodView):
    @login_required
    @bp.response(200, ReviewUpvoteSchema)
    def post(self, review_id):
        """Upvote a review"""
        return ProductSocialService.upvote_review(current_user.id, review_id)


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


@bp.route("/seller/my-products")
class SellerProducts(MethodView):
    @login_required
    @seller_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, ProductSearchResultSchema)
    def get(self, args):
        """Get seller's own products"""
        return ProductService.get_seller_products(
            seller_id=current_user.seller_account.id,
            page=args.get("page", 1),
            per_page=args.get("per_page", 20),
        )


# Note: Product image management is now handled via the media module
# Use /api/v1/media/products/{product_id}/images for image operations


# -----------------------------------------------

# TODO: Add more endpoints for:
# - Product reviews
# - Product questions
# - Bulk product operations
# - Export/import products
