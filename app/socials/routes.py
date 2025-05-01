# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, current_user

# app imports
from .schemas import StorySchema, CollectionSchema


bp = Blueprint(
    "socials", __name__, description="Socials operations", url_prefix="/socials"
)

# Social Interactions
# -----------------------------------------------
@bp.route("/stories")
class ProductStories(MethodView):
    @login_required
    @bp.response(200, StorySchema(many=True))
    def get(self):
        """View product stories"""
        # TODO: 24-hour ephemeral content
        # TODO: Story analytics
        # TODO: Interactive stickers


@bp.route("/collections")
class UserCollections(MethodView):
    @login_required
    @bp.response(200, CollectionSchema(many=True))
    def get(self):
        """Get user's product collections"""
        # TODO: Pinterest-style boards
        # TODO: Collaborative collections
        # TODO: Collection recommendations


# -----------------------------------------------
