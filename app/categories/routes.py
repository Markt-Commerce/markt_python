# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required

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
        return CategoryService.get_category_tree()

    @login_required
    @bp.arguments(CategoryCreateSchema)
    @bp.response(201, CategorySchema)
    def post(self, category_data):
        """Create new category (admin only)"""
        # TODO: Add admin check
        return CategoryService.create_category(category_data)


@bp.route("/<int:category_id>")
class CategoryDetail(MethodView):
    @bp.response(200, CategorySchema)
    def get(self, category_id):
        """Get category details"""
        return CategoryService.get_category(category_id)

    @login_required
    @bp.arguments(CategoryCreateSchema)
    @bp.response(200, CategorySchema)
    def put(self, category_data, category_id):
        """Update category (admin only)"""
        # TODO: Add admin check
        return CategoryService.update_category(category_id, category_data)


@bp.route("/<int:category_id>/products")
class CategoryProducts(MethodView):
    @bp.response(200, CategoryProductsSchema)
    def get(self, category_id):
        """Get products in category"""
        # TODO: Implement paginated product listing


@bp.route("/tags")
class TagList(MethodView):
    @bp.response(200, TagSchema(many=True))
    def get(self):
        """Get popular tags"""
        return TagService.get_popular_tags()

    @login_required
    @bp.arguments(TagSchema)
    @bp.response(201, TagSchema)
    def post(self, tag_data):
        """Create new tag (admin only)"""
        # TODO: Add admin check
        return TagService.create_tag(tag_data)
