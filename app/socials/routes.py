# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user

# project imports
from app.libs.schemas import PaginationQueryArgs
from app.libs.decorators import seller_required
from app.libs.errors import APIError

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
    # Niche schemas
    NicheSchema,
    NicheCreateSchema,
    NicheUpdateSchema,
    NicheSearchSchema,
    NicheMembershipSchema,
    NicheModerationActionSchema,
    ModerationActionSchema,
)
from .services import (
    PostService,
    FollowService,
    FeedService,
    TrendingService,
    NicheService,
)


bp = Blueprint(
    "socials", __name__, description="Social commerce operations", url_prefix="/socials"
)

# Niche/Community Routes
# -----------------------------------------------
@bp.route("/niches")
class NicheList(MethodView):
    @bp.arguments(NicheSearchSchema, location="query")
    @bp.response(200, NicheSchema(many=True))
    def get(self, args):
        """Search and list niche communities"""
        try:
            user_id = current_user.id if current_user.is_authenticated else None
            return NicheService.search_niches(args, user_id)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @seller_required
    @bp.arguments(NicheCreateSchema)
    @bp.response(201, NicheSchema)
    def post(self, niche_data):
        """Create new niche community (sellers only)"""
        try:
            return NicheService.create_niche(current_user.id, niche_data)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/niches/<niche_id>")
class NicheDetail(MethodView):
    @bp.response(200, NicheSchema)
    def get(self, niche_id):
        """Get niche details with access control"""
        try:
            user_id = current_user.id if current_user.is_authenticated else None
            return NicheService.get_niche(niche_id, user_id)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @bp.arguments(NicheUpdateSchema)
    @bp.response(200, NicheSchema)
    def put(self, niche_data, niche_id):
        """Update niche (owner only)"""
        try:
            # TODO: Implement niche update logic
            abort(501, message="Niche updates not yet implemented")
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/niches/<niche_id>/join")
class NicheJoin(MethodView):
    @login_required
    @bp.response(200, NicheMembershipSchema)
    def post(self, niche_id):
        """Join a niche community"""
        try:
            return NicheService.join_niche(niche_id, current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/niches/<niche_id>/leave")
class NicheLeave(MethodView):
    @login_required
    @bp.response(204)
    def post(self, niche_id):
        """Leave a niche community"""
        try:
            NicheService.leave_niche(niche_id, current_user.id)
            return None
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/niches/<niche_id>/members")
class NicheMembers(MethodView):
    @login_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, NicheMembershipSchema(many=True))
    def get(self, args, niche_id):
        """Get niche members with role filtering"""
        try:
            return NicheService.get_niche_members(niche_id, args)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/niches/<niche_id>/moderate")
class NicheModeration(MethodView):
    @login_required
    @bp.arguments(ModerationActionSchema)
    @bp.response(200, NicheModerationActionSchema)
    def post(self, action_data, niche_id):
        """Perform moderation action (moderators only)"""
        try:
            return NicheService.moderate_user(
                niche_id, current_user.id, action_data["target_user_id"], action_data
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/my-niches")
class MyNiches(MethodView):
    @login_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, NicheMembershipSchema(many=True))
    def get(self, args):
        """Get current user's niche memberships"""
        try:
            return NicheService.get_user_niches(current_user.id, args)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/niches/<niche_id>/can-post")
class NichePostPermission(MethodView):
    @login_required
    @bp.response(200)
    def get(self, niche_id):
        """Check if user can post in niche"""
        try:
            return NicheService.can_user_post_in_niche(niche_id, current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)


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


# Posts
# -----------------------------------------------
@bp.route("/posts")
class PostList(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, PostDetailSchema(many=True))
    def get(self, args):
        """Get paginated posts with filters"""
        return PostService.get_posts(args)

    @login_required
    @seller_required
    @bp.arguments(PostCreateSchema)
    @bp.response(201, PostDetailSchema)
    def post(self, post_data):
        """Create new post (sellers only)"""
        return PostService.create_post(current_user.seller_account.id, post_data)


@bp.route("/posts/<post_id>")
class PostDetail(MethodView):
    @bp.response(200, PostDetailSchema)
    def get(self, post_id):
        """Get post details"""
        return PostService.get_post(post_id)

    @login_required
    @bp.arguments(PostUpdateSchema)
    @bp.response(200, PostDetailSchema)
    def put(self, post_data, post_id):
        """Update post (owner only)"""
        post = PostService.get_post(post_id)
        if post.seller_id != current_user.seller_account.id:
            abort(403, message="You can only update your own posts")
        return PostService.update_post(post_id, post_data)

    @login_required
    @bp.response(204)
    def delete(self, post_id):
        """Delete post (owner only)"""
        post = PostService.get_post(post_id)
        if post.seller_id != current_user.seller_account.id:
            abort(403, message="You can only delete your own posts")
        PostService.delete_post(post_id)
        return None


@bp.route("/posts/<post_id>/status")
class PostStatusUpdate(MethodView):
    @login_required
    @bp.arguments(PostStatusUpdateSchema)
    @bp.response(200, PostDetailSchema)
    def put(self, status_data, post_id):
        """Update post status (owner only)"""
        post = PostService.get_post(post_id)
        if post.seller_id != current_user.seller_account.id:
            abort(403, message="You can only update your own posts")
        return PostService.update_post_status(post_id, status_data["status"])


@bp.route("/posts/<post_id>/like")
class PostLike(MethodView):
    @login_required
    @bp.response(200, PostLikeSchema)
    def post(self, post_id):
        """Like/unlike a post"""
        return PostService.toggle_like(current_user.id, post_id)


@bp.route("/posts/<post_id>/comments")
class PostComments(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, PostCommentsSchema)
    def get(self, args, post_id):
        """Get post comments"""
        return PostService.get_post_comments(
            post_id, args.get("page", 1), args.get("per_page", 20)
        )

    @login_required
    @bp.arguments(CommentCreateSchema)
    @bp.response(201, PostCommentSchema)
    def post(self, comment_data, post_id):
        """Create comment on post"""
        return PostService.create_comment(current_user.id, post_id, comment_data)


@bp.route("/comments/<comment_id>")
class CommentDetail(MethodView):
    @login_required
    @bp.arguments(CommentUpdateSchema)
    @bp.response(200, PostCommentSchema)
    def put(self, comment_data, comment_id):
        """Update comment (owner only)"""
        comment = PostService.get_comment(comment_id)
        if comment.user_id != current_user.id:
            abort(403, message="You can only update your own comments")
        return PostService.update_comment(comment_id, comment_data)

    @login_required
    @bp.response(204)
    def delete(self, comment_id):
        """Delete comment (owner only)"""
        comment = PostService.get_comment(comment_id)
        if comment.user_id != current_user.id:
            abort(403, message="You can only delete your own comments")
        PostService.delete_comment(comment_id)
        return None


# Seller Posts
# -----------------------------------------------
@bp.route("/seller/<seller_id>/posts")
class SellerPosts(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, SellerPostsSchema)
    def get(self, args, seller_id):
        """Get seller's posts"""
        return PostService.get_seller_posts(
            seller_id, args.get("page", 1), args.get("per_page", 20)
        )


@bp.route("/seller/posts/drafts")
class SellerDrafts(MethodView):
    @login_required
    @seller_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, PostDetailSchema(many=True))
    def get(self, args):
        """Get seller's draft posts"""
        return PostService.get_seller_drafts(
            current_user.seller_account.id,
            args.get("page", 1),
            args.get("per_page", 20),
        )


@bp.route("/seller/posts/archived")
class SellerArchived(MethodView):
    @login_required
    @seller_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, PostDetailSchema(many=True))
    def get(self, args):
        """Get seller's archived posts"""
        return PostService.get_seller_archived(
            current_user.seller_account.id,
            args.get("page", 1),
            args.get("per_page", 20),
        )


# Follows
# -----------------------------------------------
@bp.route("/follow/<followee_id>")
class FollowUser(MethodView):
    @login_required
    @bp.response(200, FollowSchema)
    def post(self, followee_id):
        """Follow a user"""
        return FollowService.follow_user(current_user.id, followee_id)

    @login_required
    @bp.response(204)
    def delete(self, followee_id):
        """Unfollow a user"""
        FollowService.unfollow_user(current_user.id, followee_id)
        return None


# Feed
# -----------------------------------------------
@bp.route("/feed")
class UserFeed(MethodView):
    @login_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, HybridFeedSchema)
    def get(self, args):
        """Get personalized feed"""
        return FeedService.get_hybrid_feed(
            current_user.id, page=args.get("page", 1), per_page=args.get("per_page", 20)
        )


@bp.route("/feed/trending")
class TrendingFeed(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, HybridFeedSchema)
    def get(self, args):
        """Get trending feed"""
        return TrendingService.get_trending_content(
            user_id=current_user.id if current_user.is_authenticated else None,
            page=args.get("page", 1),
            per_page=args.get("per_page", 20),
        )
