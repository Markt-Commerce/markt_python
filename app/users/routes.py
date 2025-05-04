# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_user, logout_user, login_required, current_user

from sqlalchemy import or_

# project imports
from app.libs.errors import AuthError, NotFoundError
from app.libs.pagination import Paginator
from app.libs.schemas import PaginationQueryArgs
from app.media.schemas import MediaSchema

# app imports
from .schemas import (
    UserSchema,
    UserRegisterSchema,
    UserLoginSchema,
    PasswordResetSchema,
    PasswordResetConfirmSchema,
    UserPaginationSchema,
    UserProfileSchema,
    FeedSchema,
    PublicProfileSchema,
    UsernameAvailableSchema,
    UsernameCheckSchema,
)
from .services import AuthService, UserService
from .models import User

bp = Blueprint("users", __name__, description="User operations", url_prefix="/users")


@bp.route("/register")
class UserRegister(MethodView):
    @bp.arguments(UserRegisterSchema)
    @bp.response(201, UserProfileSchema)
    @bp.alt_response(400, description="Validation error")
    @bp.alt_response(409, description="Email/username already exists")
    def post(self, user_data):
        try:
            user = AuthService.register_user(user_data)
            login_user(user)
            return user
        except AuthError as e:
            abort(e.status_code, message=e.message)
        except ValueError as e:
            abort(400, message=str(e))


@bp.route("/login")
class UserLogin(MethodView):
    @bp.arguments(UserLoginSchema)
    @bp.response(200, UserSchema)
    @bp.alt_response(401, description="Invalid credentials")
    def post(self, credentials):
        try:
            user = AuthService.login_user(
                credentials["email"],
                credentials["password"],
                credentials["account_type"],
            )
            login_user(user)
            return user
        except AuthError as e:
            abort(e.status_code, message=e.message)


@bp.route("/logout")
class UserLogout(MethodView):
    @login_required
    @bp.response(204)
    def post(self):
        logout_user()
        return None


@bp.route("/profile")
class UserProfile(MethodView):
    @login_required
    @bp.response(200, UserProfileSchema)
    def get(self):
        try:
            return UserService.get_user_profile(current_user.id)
        except AuthError as e:
            abort(e.status_code, message=e.message)
        except ValueError as e:
            abort(400, message=str(e))

    def patch(self):
        pass


@bp.route("/switch-role")
class SwitchRole(MethodView):
    @login_required
    @bp.response(200, UserSchema)
    def post(self):
        try:
            user = UserService.switch_role(current_user.id)
            return user
        except AuthError as e:
            abort(e.status_code, message=e.message)


@bp.route("/password-reset")
class PasswordReset(MethodView):
    @bp.arguments(PasswordResetSchema)
    @bp.response(202)
    def post(self, data):
        code = AuthService.initiate_password_reset(data["email"])
        return {"message": f"Reset code sent (DEV ONLY: {code})"}


@bp.route("/check-username")
class UsernameCheck(MethodView):
    @bp.arguments(UsernameCheckSchema, location="query")
    @bp.response(200, UsernameAvailableSchema)
    def get(self, args):
        try:
            return UserService.check_username_availability(args["username"])
        except Exception as e:
            abort(400, message=str(e))


@bp.route("/password-reset/confirm")
class PasswordResetConfirm(MethodView):
    @bp.arguments(PasswordResetConfirmSchema)
    @bp.response(204)
    def post(self, data):
        AuthService.confirm_password_reset(
            data["email"], data["code"], data["new_password"]
        )
        return None


@bp.route("/")
class UserList(MethodView):
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, UserPaginationSchema)
    def get(self, args):
        try:
            # Initialize paginator
            paginator = Paginator(
                User.query, page=args.get("page", 1), per_page=args.get("per_page", 20)
            )

            # Apply search if provided
            if "search" in args:
                search = f"%{args['search']}%"
                paginator.query = paginator.query.filter(
                    or_(User.username.ilike(search), User.email.ilike(search))
                )

            # Get paginated results
            result = paginator.paginate(args)

            return {
                "items": result["items"],
                "pagination": {
                    "page": result["page"],
                    "per_page": result["per_page"],
                    "total_items": result["total_items"],
                    "total_pages": result["total_pages"],
                },
            }
        except Exception as e:
            abort(500, message=str(e))


# Social Features
# -----------------------------------------------
@bp.route("/<user_id>/follow")
class FollowUser(MethodView):
    @login_required
    @bp.response(204)
    def post(self, user_id):
        """Follow another user"""
        # TODO: Implement follow logic
        # TODO: Add notification to followed user
        # TODO: Update follower/following counts


@bp.route("/feed")
class UserFeed(MethodView):
    @login_required
    @bp.response(200, FeedSchema(many=True))
    def get(self):
        """Get personalized feed (products + social content)"""
        # TODO: Mix products from followed sellers + social content
        # TODO: Implement algorithmic feed ranking
        # TODO: Add pagination


# -----------------------------------------------

# Profile Enhancements
# -----------------------------------------------
@bp.route("/profile/picture", methods=["POST"])
class ProfilePictureUpload(MethodView):
    @login_required
    @bp.response(200, MediaSchema)
    def post(self):
        """Upload profile picture"""
        # TODO: Integrate with media service
        # TODO: Generate different image sizes
        # TODO: Update all references to old picture


@bp.route("/<user_id>/public")
class PublicProfile(MethodView):
    @bp.response(200, PublicProfileSchema)
    def get(self, user_id):
        """View public profile"""
        # TODO: Show public profile info
        # TODO: Include social stats (followers, products)
        # TODO: Privacy controls


# -----------------------------------------------
