# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, current_user

# project imports
from app.libs.schemas import PaginationQueryArgs
from app.libs.decorators import seller_required

# app imports
from .schemas import (
    StorySchema,
    CollectionSchema,
    PostCreateSchema,
    SellerPostsSchema,
    PostDetailSchema,
    PostUpdateSchema,
    PostStatusUpdateSchema,
    PostLikeSchema,
    PostCommentSchema,
    PostCommentsSchema,
    CommentCreateSchema,
    CommentUpdateSchema,
    FollowSchema,
    FeedItemSchema,
    HybridFeedSchema,
)
from .services import PostService, FollowService, FeedService, TrendingService


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
    @seller_required
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

    @login_required
    @seller_required
    @bp.arguments(PostUpdateSchema)
    @bp.response(200, PostDetailSchema)
    def patch(self, update_data, post_id):
        """Update post details"""
        return PostService.update_post(
            post_id, current_user.seller_account.id, update_data
        )

    @login_required
    @seller_required
    @bp.arguments(PostStatusUpdateSchema)
    @bp.response(200, PostDetailSchema)
    def put(self, status_data, post_id):
        """Change post status (publish/archive/delete)"""
        return PostService.change_post_status(
            post_id, current_user.seller_account.id, status_data["action"]
        )


@bp.route("/posts/drafts")
class DraftPosts(MethodView):
    @login_required
    @seller_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, SellerPostsSchema)
    def get(self, args):
        """Get seller's draft posts"""
        return PostService.get_seller_drafts(
            current_user.seller_account.id,
            page=args.get("page", 1),
            per_page=args.get("per_page", 20),
        )


@bp.route("/posts/archived")
class ArchivedPosts(MethodView):
    @login_required
    @seller_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, SellerPostsSchema)
    def get(self, args):
        """Get seller's archived posts"""
        return PostService.get_seller_archived(
            current_user.seller_account.id,
            page=args.get("page", 1),
            per_page=args.get("per_page", 20),
        )


@bp.route("/posts/<post_id>/like")
class PostLike(MethodView):
    @login_required
    @bp.response(201, PostLikeSchema)
    def post(self, post_id):
        """Like a post"""
        return PostService.like_post(current_user.id, post_id)


@bp.route("/posts/<post_id>/comments")
class PostComments(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, PostCommentsSchema)
    def get(self, args, post_id):
        """Get post comments"""
        return PostService.get_post_comments(
            post_id, page=args.get("page", 1), per_page=args.get("per_page", 20)
        )

    @login_required
    @bp.arguments(CommentCreateSchema)
    @bp.response(201, PostCommentSchema)
    def post(self, comment_data, post_id):
        """Add comment to post"""
        return PostService.add_comment(
            current_user.id,
            post_id,
            comment_data["content"],
            comment_data.get("parent_id"),
        )


@bp.route("/comments/<comment_id>")
class CommentDetail(MethodView):
    @login_required
    @bp.arguments(CommentUpdateSchema)
    @bp.response(200, PostCommentSchema)
    def patch(self, update_data, comment_id):
        """Update comment"""
        return PostService.update_comment(
            comment_id, current_user.id, update_data["content"]
        )

    @login_required
    @bp.response(204)
    def delete(self, comment_id):
        """Delete comment"""
        PostService.delete_comment(comment_id, current_user.id)
        return "", 204


@bp.route("/users/<user_id>/follow")
class FollowUser(MethodView):
    @login_required
    @bp.response(201, FollowSchema)
    def post(self, user_id):
        """Follow another user"""
        return FollowService.follow_user(current_user.id, user_id)


@bp.route("/sellers/<seller_id>/posts")
class SellerPosts(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, SellerPostsSchema)
    def get(self, args, seller_id):
        """Get posts by a specific seller"""
        return PostService.get_seller_posts(
            seller_id, page=args.get("page", 1), per_page=args.get("per_page", 20)
        )


@bp.route("/feed")
class UserFeed(MethodView):
    @login_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, HybridFeedSchema)
    def get(self, args):
        """Get personalized hybrid feed"""
        return FeedService.get_hybrid_feed(
            current_user.id, page=args.get("page", 1), per_page=args.get("per_page", 20)
        )


@bp.route("/feed/trending")
class TrendingFeed(MethodView):
    @bp.response(200, FeedItemSchema(many=True))
    def get(self):
        """Get trending feed"""
        return TrendingService.get_trending_content(
            current_user.id if current_user.is_authenticated else None
        )
