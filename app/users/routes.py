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
    PublicProfileSchema,
    UsernameAvailableSchema,
    UsernameCheckSchema,
    BuyerCreateSchema,
    SellerCreateSchema,
    UserUpdateSchema,
    BuyerUpdateSchema,
    SellerUpdateSchema,
    SettingsSchema,
    SettingsUpdateSchema,
)
from .services import AuthService, UserService, AccountService
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

    @login_required
    @bp.arguments(UserUpdateSchema)
    @bp.response(200, UserProfileSchema)
    def patch(self, data):
        """Update user profile"""
        try:
            updated_user = UserService.update_user_profile(current_user.id, data)
            return UserService.get_user_profile(updated_user.id)
        except AuthError as e:
            abort(e.status_code, message=e.message)


@bp.route("/create-buyer")
class CreateBuyerAccount(MethodView):
    @login_required
    @bp.arguments(BuyerCreateSchema)
    @bp.response(201, UserProfileSchema)
    def post(self, data):
        """Create buyer account for existing user"""
        try:
            if current_user.is_buyer:
                abort(400, message="Buyer account already exists")

            AccountService.create_buyer_account(current_user.id, data)
            return UserService.get_user_profile(current_user.id)
        except AuthError as e:
            abort(e.status_code, message=e.message)


@bp.route("/create-seller")
class CreateSellerAccount(MethodView):
    @login_required
    @bp.arguments(SellerCreateSchema)
    @bp.response(201, UserProfileSchema)
    def post(self, data):
        """Create seller account for existing user"""
        try:
            if current_user.is_seller:
                abort(400, message="Seller account already exists")

            AccountService.create_seller_account(current_user.id, data)
            return UserService.get_user_profile(current_user.id)
        except AuthError as e:
            abort(e.status_code, message=e.message)


@bp.route("/profile/buyer")
class BuyerProfile(MethodView):
    @login_required
    @bp.arguments(BuyerUpdateSchema)
    @bp.response(200, UserProfileSchema)
    def patch(self, data):
        """Update buyer profile"""
        try:
            if not current_user.is_buyer:
                abort(400, message="Buyer account not found")

            UserService.update_buyer_profile(current_user.id, data)
            return UserService.get_user_profile(current_user.id)
        except AuthError as e:
            abort(e.status_code, message=e.message)


@bp.route("/profile/seller")
class SellerProfile(MethodView):
    @login_required
    @bp.arguments(SellerUpdateSchema)
    @bp.response(200, UserProfileSchema)
    def patch(self, data):
        """Update seller profile"""
        try:
            if not current_user.is_seller:
                abort(400, message="Seller account not found")

            UserService.update_seller_profile(current_user.id, data)
            return UserService.get_user_profile(current_user.id)
        except AuthError as e:
            abort(e.status_code, message=e.message)


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
            return UserService.list_users(args)
        except Exception as e:
            abort(500, message=str(e))


@bp.route("/settings")
class UserSettings(MethodView):
    @login_required
    @bp.response(200, SettingsSchema)
    def get(self):
        """Get user settings"""

    @login_required
    @bp.arguments(SettingsUpdateSchema)
    @bp.response(200, SettingsSchema)
    def patch(self, data):
        """Update user settings"""


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
