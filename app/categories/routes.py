from flask_smorest import Blueprint
from flask.views import MethodView
from .services import CategoryService, TagService
from .schemas import CategorySchema, TagSchema

bp = Blueprint(
    "categories", __name__, description="Category operations", url_prefix="/categories"
)


@bp.route("/")
class CategoryList(MethodView):
    @bp.response(200, CategorySchema(many=True))
    def get(self):
        """Get category hierarchy"""
        return CategoryService.get_category_tree()


@bp.route("/tags")
class PopularTags(MethodView):
    @bp.response(200, TagSchema(many=True))
    def get(self):
        """Get popular tags"""
        return TagService.get_popular_tags()
