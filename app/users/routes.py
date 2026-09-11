import logging

# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_user, logout_user, login_required, current_user

from sqlalchemy import or_

# project imports
from flask import jsonify, make_response, current_app

from app.libs.errors import (
    AuthError,
    NotFoundError,
    UnverifiedEmailError,
    APIError,
    ConflictError,
)
from app.libs.auth_tokens import generate_auth_token
from .oauth import verify_google, verify_apple, OAuthError
from .verification import VerificationThrottled
from app.libs.pagination import Paginator
from app.libs.schemas import PaginationQueryArgs
from app.media.schemas import MediaSchema
from app.libs.decorators import login_required, seller_required

# app imports
from .schemas import (
    UserSchema,
    UserRegisterSchema,
    UserLoginSchema,
    PasswordResetSchema,
    PasswordResetConfirmSchema,
    PasswordResetResponseSchema,
    EmailVerificationSendSchema,
    EmailVerificationSchema,
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
    RoleSwitchSchema,
    StartCardsResponseSchema,
    AnalyticsOverviewSchema,
    AnalyticsTimeseriesResponseSchema,
    AnalyticsTimeseriesQuerySchema,
    AnalyticsOverviewQuerySchema,
    AddressSchema,
    AddressUpdateSchema,
    AccountDeletionPreviewSchema,
    AccountDeletionRequestSchema,
    AccountDeletionResponseSchema,
    OAuthSignInSchema,
    ShopSearchArgs,
)
from .services import (
    AuthService,
    UserService,
    AccountService,
    PublicProfileService,
    AccountDeletionService,
    SellerStartCardsService,
    SellerAnalyticsService,
    SocialAuthService,
)
from .models import User

logger = logging.getLogger(__name__)

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
            user.access_token = generate_auth_token(user.id)
            return user
        except ConflictError as e:
            abort(e.status_code, message=e.message)
        except AuthError as e:
            abort(e.status_code, message=e.message)
        except ValueError as e:
            abort(400, message=str(e))


@bp.route("/auth/oauth")
class OAuthSignIn(MethodView):
    """Sign in (or sign up) with a verified Google or Apple identity.

    One endpoint for both providers and for both new and returning users: the
    app cannot know which of those it is until the token is verified, and
    making it guess would mean a wrong guess becomes a dead end mid sign-in.

    Returns the same bearer token the password path issues, so every existing
    consumer of `access_token` is unchanged.
    """

    @bp.arguments(OAuthSignInSchema)
    @bp.response(200, UserSchema)
    @bp.alt_response(401, description="Token could not be verified")
    @bp.alt_response(409, description="Email belongs to an existing account")
    @bp.alt_response(503, description="Social sign-in not configured")
    def post(self, data):
        provider = data["provider"]
        try:
            if provider == "google":
                identity = verify_google(
                    data["identity_token"],
                    audiences=current_app.config["GOOGLE_AUDIENCES"],
                    nonce=data.get("nonce"),
                )
            else:
                identity = verify_apple(
                    data["identity_token"],
                    audiences=current_app.config["APPLE_AUDIENCES"],
                    nonce=data.get("nonce"),
                )
        except OAuthError as e:
            abort(e.status_code, message=e.message, errors={"code": e.code})

        try:
            user, created = SocialAuthService.authenticate(
                identity, name_hint=data.get("full_name")
            )
        except ConflictError as e:
            # The app turns this into "sign in with your password once to
            # connect Google", so the code matters as much as the message.
            abort(409, message=e.message, errors={"code": "ACCOUNT_EXISTS"})
        except (ValidationError, AuthError) as e:
            abort(getattr(e, "status_code", 400), message=str(getattr(e, "message", e)))

        login_user(user)
        user.access_token = generate_auth_token(user.id)

        try:
            from app.signals import daily_login

            daily_login.send("users", user_id=user.id)
        except Exception as e:
            logger.warning(f"gamification daily_login emit failed: {e}")

        return user


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
                credentials.get("account_type"),  # Use .get() to handle optional field
            )
            login_user(user)
            user.access_token = generate_auth_token(user.id)
            # Gamification: first login of the day (idempotent per day).
            try:
                from app.signals import daily_login

                daily_login.send("users", user_id=user.id)
            except Exception as e:
                logger.warning(f"gamification daily_login emit failed: {e}")
            return user
        except UnverifiedEmailError as e:
            # Return structured payload that frontend can detect easily
            abort(e.status_code, **e.to_dict())
        except AuthError as e:
            abort(e.status_code, message=e.message)


@bp.route("/logout")
class UserLogout(MethodView):
    @login_required
    @bp.response(204)
    def post(self):
        logout_user()
        return None


@bp.route("/account/deletion-check")
class AccountDeletionCheck(MethodView):
    @login_required
    @bp.response(200, AccountDeletionPreviewSchema)
    def get(self):
        """Report whether this account can be deleted, and why not if it can't.

        Lets the settings screen explain the problem (money still in the
        wallet, orders in flight) up front instead of failing the delete.
        """
        try:
            blockers = AccountDeletionService.check_blockers(current_user.id)
            return {"can_delete": not blockers, "blockers": blockers}
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/account")
class AccountDeletion(MethodView):
    @login_required
    @bp.arguments(AccountDeletionRequestSchema)
    @bp.response(200, AccountDeletionResponseSchema)
    def delete(self, data):
        """Permanently delete the signed-in user's account.

        Required by Apple App Store guideline 5.1.1(v): an account created in
        the app has to be deletable from inside the app, and deactivation does
        not satisfy it. Personal data is destroyed; posts, reviews and order
        history survive attributed to a deleted user so other people's records
        stay intact (see AccountDeletionService).
        """
        user_id = current_user.id
        try:
            result = AccountDeletionService.delete_account(user_id, data["password"])
        except ConflictError as e:
            # Built by hand rather than via abort(): flask-smorest's error
            # handler renders only message/status/code and silently drops extra
            # kwargs, so the blocker list never reached the client. The client
            # needs the structured list to say *which* order or balance is in
            # the way, not just a sentence.
            blockers = (e.payload or {}).get("blockers") or []
            return make_response(
                jsonify(
                    {
                        "code": 409,
                        "status": "Conflict",
                        "message": e.message,
                        "blockers": blockers,
                    }
                ),
                409,
            )
        except APIError as e:
            abort(e.status_code, message=e.message)

        # Drop the session cookie too. Bearer tokens are stateless, so they
        # are refused by the loaders in main.setup on the strength of
        # deleted_at rather than being revoked here.
        logout_user()
        return result


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
        except ConflictError as e:
            abort(e.status_code, message=e.message)
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
    @bp.response(200, RoleSwitchSchema)
    def post(self):
        try:
            result = UserService.switch_role(current_user.id)
            return result
        except AuthError as e:
            abort(e.status_code, message=e.message)


@bp.route("/password-reset")
class PasswordReset(MethodView):
    @bp.arguments(PasswordResetSchema)
    @bp.response(202, PasswordResetResponseSchema)
    def post(self, data):
        """Initiate password reset process"""
        try:
            AuthService.initiate_password_reset(data["email"])
            return {
                "message": "If the email exists, a password reset code has been sent"
            }
        except AuthError as e:
            abort(e.status_code, message=e.message)
        except Exception as e:
            logger.error(f"Password reset error: {str(e)}")
            abort(500, message="Failed to process password reset request")


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
    @bp.response(200, PasswordResetResponseSchema)
    def post(self, data):
        """Confirm password reset with code and new password"""
        try:
            AuthService.confirm_password_reset(
                data["email"], data["code"], data["new_password"]
            )
            return {"message": "Password reset successfully"}
        except AuthError as e:
            abort(e.status_code, message=e.message)
        except Exception as e:
            logger.error(f"Password reset confirmation error: {str(e)}")
            abort(500, message="Failed to reset password")


@bp.route("/email-verification/send")
class SendEmailVerification(MethodView):
    @bp.arguments(EmailVerificationSendSchema)
    @bp.response(202, PasswordResetResponseSchema)
    def post(self, data):
        """Send email verification code"""
        try:
            AuthService.send_email_verification(data["email"])
            return {"message": "Verification email sent"}
        except VerificationThrottled as e:
            # A rate limit is 429, not 500. A 500 tells the app we broke
            # when what we mean is "slow down", and the client has no way
            # to tell the difference or know when to retry.
            abort(429, message=e.message, errors={"retry_after": e.retry_after})
        except AuthError as e:
            abort(e.status_code, message=e.message)
        except Exception as e:
            abort(500, message=str(e))


@bp.route("/email-verification/verify")
class VerifyEmail(MethodView):
    @bp.arguments(EmailVerificationSchema)
    @bp.response(200, PasswordResetResponseSchema)
    def post(self, data):
        """Verify email with code"""
        try:
            AuthService.verify_email(data["email"], data["verification_code"])
            return {"message": "Email verified successfully"}
        except VerificationThrottled as e:
            # A rate limit is 429, not 500. A 500 tells the app we broke
            # when what we mean is "slow down", and the client has no way
            # to tell the difference or know when to retry.
            abort(429, message=e.message, errors={"retry_after": e.retry_after})
        except AuthError as e:
            abort(e.status_code, message=e.message)
        except Exception as e:
            abort(500, message=str(e))


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


@bp.route("/address")
class UserAddressUpdate(MethodView):
    @login_required
    @bp.arguments(AddressUpdateSchema)
    @bp.response(200, AddressSchema)
    def patch(self, data):
        """Create or update the current user's address (used for seller pickup logistics)."""
        try:
            address = UserService.upsert_user_address(current_user.id, data)
            return address
        except AuthError as e:
            abort(e.status_code, message=e.message)


@bp.route("/profile/picture", methods=["POST"])
class ProfilePictureUpload(MethodView):
    @login_required
    @bp.response(200, MediaSchema)
    def post(self):
        """Upload profile picture"""
        try:
            from flask import request
            from werkzeug.utils import secure_filename
            from io import BytesIO

            # Check if file is present
            if "file" not in request.files:
                abort(400, message="No file provided")

            file = request.files["file"]
            if file.filename == "":
                abort(400, message="No file selected")

            # Validate file
            filename = secure_filename(file.filename)
            if not filename:
                abort(400, message="Invalid filename")

            # Read file into memory
            file_stream = BytesIO(file.read())
            file_stream.seek(0)

            # Upload profile picture
            result = UserService.upload_profile_picture(
                user_id=current_user.id, file_stream=file_stream, filename=filename
            )

            return result["media"]

        except AuthError as e:
            abort(e.status_code, message=e.message)
        except Exception as e:
            logger.error(f"Unexpected error in profile picture upload: {e}")
            abort(500, message="Internal server error")


@bp.route("/profile/seller/banner", methods=["POST"])
class ShopBannerUpload(MethodView):
    @login_required
    @bp.response(200, MediaSchema)
    def post(self):
        """Upload the shop's cover image."""
        try:
            from flask import request
            from werkzeug.utils import secure_filename
            from io import BytesIO

            if not current_user.is_seller:
                abort(400, message="Seller account not found")

            if "file" not in request.files:
                abort(400, message="No file provided")

            file = request.files["file"]
            if file.filename == "":
                abort(400, message="No file selected")

            filename = secure_filename(file.filename)
            if not filename:
                abort(400, message="Invalid filename")

            file_stream = BytesIO(file.read())
            file_stream.seek(0)

            result = UserService.upload_shop_banner(
                user_id=current_user.id, file_stream=file_stream, filename=filename
            )
            return result["media"]

        except AuthError as e:
            abort(e.status_code, message=e.message)
        except Exception as e:
            logger.error(f"Unexpected error in shop banner upload: {e}")
            abort(500, message="Internal server error")


@bp.route("/<user_id>/public")
class PublicProfile(MethodView):
    @bp.response(200, PublicProfileSchema)
    def get(self, user_id):
        """Public view of another user.

        Was a stub -- three TODOs, no return, and an empty schema -- so it
        500'd for anyone who called it. Nothing did, which is why the feed's
        post-author header still links nowhere.

        Deliberately open to anonymous callers (a shared product link should
        render its seller), which is exactly why the schema is narrow.
        """
        try:
            return PublicProfileService.get_public_profile(
                user_id,
                viewer_id=current_user.id if current_user.is_authenticated else None,
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/shops")
class ShopList(MethodView):
    @bp.arguments(ShopSearchArgs, location="query")
    @bp.response(200, description="List of shops")
    def get(self, args):
        """Search and discover shops.

        Pass `latitude`/`longitude` with `sort_by=nearby` to rank by distance;
        each shop then carries `distance_km`, and `location.radius_km` says
        which rung of the fallback ladder answered.
        """
        try:
            from .services import ShopService

            user_id = current_user.id if current_user.is_authenticated else None
            return ShopService.search_shops(args, user_id)
        except Exception as e:
            abort(500, message=str(e))


@bp.route("/shops/trending")
class TrendingShops(MethodView):
    @bp.response(200, description="Trending shops")
    def get(self):
        """Get trending shops"""
        try:
            from .services import ShopService

            shops = ShopService.get_trending_shops()
            return {"shops": shops}
        except Exception as e:
            abort(500, message=str(e))


@bp.route("/shops/categories")
class ShopCategories(MethodView):
    @bp.response(200, description="Shop categories")
    def get(self):
        """Get all shop categories for filtering"""
        try:
            from .services import ShopService

            categories = ShopService.get_shop_categories()
            return {"categories": categories}
        except Exception as e:
            abort(500, message=str(e))


@bp.route("/shops/<int:shop_id>")
class ShopDetail(MethodView):
    @bp.response(200, description="Shop details")
    def get(self, shop_id):
        """Get detailed shop information"""
        try:
            from .services import ShopService

            user_id = current_user.id if current_user.is_authenticated else None
            return ShopService.get_shop_details(shop_id, user_id)
        except NotFoundError as e:
            abort(404, message=str(e))
        except Exception as e:
            abort(500, message=str(e))


# -----------------------------------------------


# Seller Dashboard Endpoints
@bp.route("/sellers/start-cards")
class SellerStartCards(MethodView):
    @login_required
    @seller_required
    @bp.response(200, StartCardsResponseSchema)
    def get(self):
        """Get seller onboarding/start cards with completion status"""
        try:
            seller_id = current_user.seller_account.id
            return SellerStartCardsService.get_seller_start_cards(seller_id)
        except Exception as e:
            logger.error(f"Failed to get seller start cards: {str(e)}")
            abort(500, message="Failed to get seller start cards")


@bp.route("/sellers/analytics/overview")
class SellerAnalyticsOverview(MethodView):
    @login_required
    @seller_required
    @bp.arguments(AnalyticsOverviewQuerySchema, location="query")
    @bp.response(200, AnalyticsOverviewSchema)
    def get(self, args):
        """Get seller analytics overview for dashboard header"""
        try:
            seller_id = current_user.seller_account.id
            window_days = args.get("window_days", 30)
            return SellerAnalyticsService.get_seller_analytics_overview(
                seller_id, window_days
            )
        except Exception as e:
            logger.error(f"Failed to get seller analytics overview: {str(e)}")
            abort(500, message="Failed to get seller analytics overview")


@bp.route("/sellers/analytics/timeseries")
class SellerAnalyticsTimeseries(MethodView):
    @login_required
    @seller_required
    @bp.arguments(AnalyticsTimeseriesQuerySchema, location="query")
    @bp.response(200, AnalyticsTimeseriesResponseSchema)
    def get(self, args):
        """Get time-bucketed seller analytics data for graphs"""
        try:
            seller_id = current_user.seller_account.id
            metric = args["metric"]
            bucket = args["bucket"]
            start_date = args["start_date"]
            end_date = args["end_date"]

            return SellerAnalyticsService.get_seller_analytics_timeseries(
                seller_id, metric, bucket, start_date, end_date
            )
        except Exception as e:
            logger.error(f"Failed to get seller analytics timeseries: {str(e)}")
            abort(500, message="Failed to get seller analytics timeseries")


# -----------------------------------------------
