# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required
from flask import request

# project imports
from app.libs.schemas import PaginationQueryArgs
from app.libs.errors import APIError

# app imports
from .services import CategoryService, TagService
from .schemas import (
    CategorySchema,
    CategoryTreeSchema,
    CategoryCreateSchema,
    TagSchema,
    CategoryProductsSchema,
)

bp = Blueprint(
    "categories", __name__, description="Category operations", url_prefix="/categories"
)


@bp.route("/")
class CategoryList(MethodView):
    @bp.response(200, CategoryTreeSchema(many=True))
    def get(self):
        """Get category hierarchy"""
        try:
            return CategoryService.get_category_tree()
        except Exception as e:
            abort(500, message=f"Failed to fetch categories: {str(e)}")

    @login_required
    @bp.arguments(CategoryCreateSchema)
    @bp.response(201, CategorySchema)
    def post(self, category_data):
        """Create new category (admin only)"""
        # TODO: Add admin check
        try:
            return CategoryService.create_category(category_data)
        except APIError as e:
            abort(e.status_code, message=e.message)
        except Exception as e:
            abort(500, message=f"Failed to create category: {str(e)}")


@bp.route("/<int:category_id>")
class CategoryDetail(MethodView):
    @bp.response(200, CategorySchema)
    def get(self, category_id):
        """Get category details"""
        try:
            category = CategoryService.get_category(category_id)
            if not category:
                abort(404, message="Category not found")
            return category
        except APIError as e:
            abort(e.status_code, message=e.message)
        except Exception as e:
            abort(500, message=f"Failed to fetch category: {str(e)}")

    @login_required
    @bp.arguments(CategoryCreateSchema)
    @bp.response(200, CategorySchema)
    def put(self, category_data, category_id):
        """Update category (admin only)"""
        # TODO: Add admin check
        try:
            return CategoryService.update_category(category_id, category_data)
        except APIError as e:
            abort(e.status_code, message=e.message)
        except Exception as e:
            abort(500, message=f"Failed to update category: {str(e)}")


@bp.route("/<int:category_id>/products")
class CategoryProducts(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, CategoryProductsSchema)
    def get(self, args, category_id):
        """Get products in category with pagination"""
        try:
            return CategoryService.get_category_products(
                category_id, page=args.get("page", 1), per_page=args.get("per_page", 20)
            )
        except APIError as e:
            abort(e.status_code, message=e.message)
        except Exception as e:
            abort(500, message=f"Failed to fetch category products: {str(e)}")


@bp.route("/tags")
class TagList(MethodView):
    @bp.response(200, TagSchema(many=True))
    def get(self):
        """Get popular tags"""
        try:
            return TagService.get_popular_tags()
        except Exception as e:
            abort(500, message=f"Failed to fetch tags: {str(e)}")

    @login_required
    @bp.arguments(TagSchema)
    @bp.response(201, TagSchema)
    def post(self, tag_data):
        """Create new tag (admin only)"""
        # TODO: Add admin check
        try:
            return TagService.create_tag(tag_data)
        except APIError as e:
            abort(e.status_code, message=e.message)
        except Exception as e:
            abort(500, message=f"Failed to create tag: {str(e)}")
