# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, current_user

# app imports
from .schemas import (
    StorySchema,
    CollectionSchema,
    PostCreateSchema,
    PostSchema,
    PostDetailSchema,
    PostLikeSchema,
    PostCommentSchema,
    FollowSchema,
    FeedItemSchema,
)
from .services import PostService, FollowService, FeedService


bp = Blueprint(
    "socials", __name__, description="Social commerce operations", url_prefix="/socials"
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


@bp.route("/posts")
class PostList(MethodView):
    @login_required
    @bp.arguments(PostCreateSchema)
    @bp.response(201, PostDetailSchema)
    def post(self, post_data):
        """Create a new post"""
        return PostService.create_post(current_user.seller_account.id, post_data)


@bp.route("/posts/<post_id>")
class PostDetail(MethodView):
    @bp.response(200, PostDetailSchema)
    def get(self, post_id):
        """Get post details"""
        return PostService.get_post(post_id)


@bp.route("/posts/<post_id>/like")
class PostLike(MethodView):
    @login_required
    @bp.response(201, PostLikeSchema)
    def post(self, post_id):
        """Like a post"""
        return PostService.like_post(current_user.id, post_id)


@bp.route("/users/<user_id>/follow")
class FollowUser(MethodView):
    @login_required
    @bp.response(201, FollowSchema)
    def post(self, user_id):
        """Follow another user"""
        return FollowService.follow_user(current_user.id, user_id)


@bp.route("/feed")
class UserFeed(MethodView):
    @login_required
    @bp.response(200, FeedItemSchema(many=True))
    def get(self):
        """Get personalized feed"""
        return FeedService.get_user_feed(current_user.id)
