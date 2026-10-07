"""Admin API surface, mounted at /api/v1/admin.

Increment 1 establishes the module and the RBAC/audit foundations; §1 user
management and §2 seller verification land on this same blueprint in the
following increments.
"""

from io import BytesIO

from flask import request
from flask.views import MethodView
from flask_login import current_user
from flask_smorest import Blueprint, abort
from werkzeug.utils import secure_filename

from app.libs.decorators import (
    login_required,
    rate_limit,
    require_permission,
    staff_required,
)
from app.libs.errors import APIError
from app.users.verification import VerificationThrottled

from .auth_services import AdminAuthService, admin_me_payload
from .permissions import Permission
from .schemas import (
    AdminLoginResponseSchema,
    AdminLoginSchema,
    AdminMeSchema,
    AdminReasonSchema,
    AdminResendVerificationResponseSchema,
    AdminSellerDetailSchema,
    AdminSellerListQuerySchema,
    AdminSellerListResponseSchema,
    AdminSellerMarketReviewSchema,
    AdminSellerPayoutEditSchema,
    AdminSellerRejectSchema,
    AdminSellerVerifySchema,
    AdminUserDetailSchema,
    AdminUserEditSchema,
    AdminUserListQuerySchema,
    AdminUserListResponseSchema,
    AdminUserRolesSchema,
    AdminUserStaffRoleSchema,
)
from .seller_services import AdminSellerService
from .services import AdminUserService

bp = Blueprint(
    "admin",
    __name__,
    description="Admin operations",
    url_prefix="/admin",
)


@bp.route("/me")
class AdminMe(MethodView):
    @login_required
    @staff_required
    @bp.response(200, AdminMeSchema)
    def get(self):
        """The signed-in staff member's role and resolved permissions."""
        return admin_me_payload(current_user)


# ==================== Staff sign-in ====================


@bp.route("/auth/login")
class AdminLogin(MethodView):
    @rate_limit(10)
    @bp.arguments(AdminLoginSchema)
    @bp.response(200, AdminLoginResponseSchema)
    @bp.alt_response(401, description="Invalid credentials or blocked account")
    @bp.alt_response(403, description="Not staff, or email not verified")
    def post(self, credentials):
        """Sign a staff member in to the admin console.

        Unlike /users/login this needs no buyer or seller profile, and sends
        no verification code. Returns a bearer token plus the /admin/me body.
        """
        try:
            return AdminAuthService.login(credentials["email"], credentials["password"])
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/auth/logout")
class AdminLogout(MethodView):
    @login_required
    @bp.response(204)
    def post(self):
        """Sign out by revoking every bearer token this account holds."""
        AdminAuthService.logout(current_user.id)
        return None


# ==================== §1 User management ====================


@bp.route("/users")
class AdminUsers(MethodView):
    @login_required
    @require_permission(Permission.USER_VIEW)
    @bp.arguments(AdminUserListQuerySchema, location="query")
    @bp.response(200, AdminUserListResponseSchema)
    def get(self, args):
        """List/search users, filterable by role and account status."""
        return AdminUserService.list_users(
            q=args.get("q"),
            role=args.get("role"),
            status=args.get("status"),
            page=args.get("page", 1),
            per_page=args.get("per_page", 20),
        )


@bp.route("/users/<user_id>")
class AdminUserDetail(MethodView):
    @login_required
    @require_permission(Permission.USER_VIEW)
    @bp.response(200, AdminUserDetailSchema)
    def get(self, user_id):
        """Full detail for one user, including buyer/seller sub-profiles."""
        try:
            return AdminUserService.get_user(user_id)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @require_permission(Permission.USER_EDIT)
    @bp.arguments(AdminUserEditSchema)
    @bp.response(200, AdminUserDetailSchema)
    def patch(self, data, user_id):
        """Correct basic profile fields (phone, username, avatar)."""
        try:
            return AdminUserService.edit_profile(current_user, user_id, data)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/users/<user_id>/profile-picture")
class AdminUserProfilePicture(MethodView):
    @login_required
    @require_permission(Permission.USER_EDIT)
    @bp.response(200, AdminUserDetailSchema)
    @bp.alt_response(400, description="No file in the request")
    @bp.alt_response(422, description="Not a usable image")
    def post(self, user_id):
        """Replace a user's profile picture (multipart/form-data, field
        ``file``). JPEG, PNG, WebP or GIF, up to 10 MB."""
        file = request.files.get("file")
        if not file or not file.filename:
            abort(400, message="No file provided")
        filename = secure_filename(file.filename)
        if not filename:
            abort(400, message="Invalid filename")
        try:
            return AdminUserService.upload_profile_picture(
                current_user, user_id, BytesIO(file.read()), filename
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/users/<user_id>/suspend")
class AdminUserSuspend(MethodView):
    @login_required
    @require_permission(Permission.USER_SUSPEND)
    @bp.arguments(AdminReasonSchema)
    @bp.response(200, AdminUserDetailSchema)
    def post(self, data, user_id):
        """Temporarily suspend an account (blocks auth immediately)."""
        try:
            return AdminUserService.suspend_user(
                current_user, user_id, data.get("reason")
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/users/<user_id>/reinstate")
class AdminUserReinstate(MethodView):
    @login_required
    @require_permission(Permission.USER_SUSPEND)
    @bp.arguments(AdminReasonSchema)
    @bp.response(200, AdminUserDetailSchema)
    def post(self, data, user_id):
        """Lift a suspension."""
        try:
            return AdminUserService.reinstate_user(
                current_user, user_id, data.get("reason")
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/users/<user_id>/ban")
class AdminUserBan(MethodView):
    @login_required
    @require_permission(Permission.USER_BAN)
    @bp.arguments(AdminReasonSchema)
    @bp.response(200, AdminUserDetailSchema)
    def post(self, data, user_id):
        """Ban an account (blocks auth immediately)."""
        try:
            return AdminUserService.ban_user(current_user, user_id, data.get("reason"))
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/users/<user_id>/unban")
class AdminUserUnban(MethodView):
    @login_required
    @require_permission(Permission.USER_BAN)
    @bp.arguments(AdminReasonSchema)
    @bp.response(200, AdminUserDetailSchema)
    def post(self, data, user_id):
        """Lift a ban."""
        try:
            return AdminUserService.unban_user(
                current_user, user_id, data.get("reason")
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/users/<user_id>/verify-email")
class AdminUserVerifyEmail(MethodView):
    @login_required
    @require_permission(Permission.USER_VERIFY_EMAIL)
    @bp.response(200, AdminUserDetailSchema)
    def post(self, user_id):
        """Force-mark a user's email as verified (support fix)."""
        try:
            return AdminUserService.force_verify_email(current_user, user_id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/users/<user_id>/resend-verification")
class AdminUserResendVerification(MethodView):
    @login_required
    @require_permission(Permission.USER_VERIFY_EMAIL)
    @bp.response(200, AdminResendVerificationResponseSchema)
    def post(self, user_id):
        """Send the user a fresh email-verification code."""
        try:
            return AdminUserService.resend_verification(current_user, user_id)
        except VerificationThrottled as e:
            abort(
                429,
                message=e.message,
                errors={"retry_after": e.retry_after},
                headers={"Retry-After": str(e.retry_after)},
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/users/<user_id>/force-logout")
class AdminUserForceLogout(MethodView):
    @login_required
    @require_permission(Permission.USER_FORCE_LOGOUT)
    @bp.arguments(AdminReasonSchema)
    @bp.response(200, AdminUserDetailSchema)
    def post(self, data, user_id):
        """Invalidate all of a user's bearer tokens (force re-login)."""
        try:
            return AdminUserService.force_logout(
                current_user, user_id, data.get("reason")
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/users/<user_id>/roles")
class AdminUserRoles(MethodView):
    @login_required
    @require_permission(Permission.USER_MANAGE_ROLES)
    @bp.arguments(AdminUserRolesSchema)
    @bp.response(200, AdminUserDetailSchema)
    def post(self, data, user_id):
        """Enable/disable a user's buyer and/or seller roles."""
        try:
            return AdminUserService.manage_roles(
                current_user,
                user_id,
                is_buyer=data.get("is_buyer"),
                is_seller=data.get("is_seller"),
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/users/<user_id>/staff-role")
class AdminUserStaffRole(MethodView):
    @login_required
    @require_permission(Permission.USER_MANAGE_STAFF)
    @bp.arguments(AdminUserStaffRoleSchema)
    @bp.response(200, AdminUserDetailSchema)
    def post(self, data, user_id):
        """Grant, change or remove a user's staff role (super admins only)."""
        try:
            return AdminUserService.set_staff_role(
                current_user, user_id, data["admin_role"], data.get("reason")
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


# ==================== §2 Seller verification & shop ====================


@bp.route("/sellers")
class AdminSellers(MethodView):
    @login_required
    @require_permission(Permission.SELLER_VIEW)
    @bp.arguments(AdminSellerListQuerySchema, location="query")
    @bp.response(200, AdminSellerListResponseSchema)
    def get(self, args):
        """Verification queue / shop directory, filterable by verification
        status, market-verification status, active and featured flags."""
        return AdminSellerService.list_sellers(
            q=args.get("q"),
            verification_status=args.get("verification_status"),
            market_status=args.get("market_status"),
            is_active=args.get("is_active"),
            is_featured=args.get("is_featured"),
            page=args.get("page", 1),
            per_page=args.get("per_page", 20),
        )


@bp.route("/sellers/<int:seller_id>")
class AdminSellerDetail(MethodView):
    @login_required
    @require_permission(Permission.SELLER_VIEW)
    @bp.response(200, AdminSellerDetailSchema)
    def get(self, seller_id):
        """Full shop detail incl. verification data, payout and market info."""
        try:
            return AdminSellerService.get_seller(seller_id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/sellers/<int:seller_id>/verify")
class AdminSellerVerify(MethodView):
    @login_required
    @require_permission(Permission.SELLER_VERIFY)
    @bp.arguments(AdminSellerVerifySchema)
    @bp.response(200, AdminSellerDetailSchema)
    def post(self, data, seller_id):
        """Approve a shop's verification."""
        try:
            return AdminSellerService.verify_seller(
                current_user, seller_id, data.get("note")
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/sellers/<int:seller_id>/reject")
class AdminSellerReject(MethodView):
    @login_required
    @require_permission(Permission.SELLER_VERIFY)
    @bp.arguments(AdminSellerRejectSchema)
    @bp.response(200, AdminSellerDetailSchema)
    def post(self, data, seller_id):
        """Reject a shop's verification (reason required)."""
        try:
            return AdminSellerService.reject_seller(
                current_user, seller_id, data["reason"]
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/sellers/<int:seller_id>/suspend")
class AdminSellerSuspend(MethodView):
    @login_required
    @require_permission(Permission.SELLER_SUSPEND)
    @bp.arguments(AdminReasonSchema)
    @bp.response(200, AdminSellerDetailSchema)
    def post(self, data, seller_id):
        """Stop a shop selling (deactivates the seller account)."""
        try:
            return AdminSellerService.suspend_seller(
                current_user, seller_id, data.get("reason")
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/sellers/<int:seller_id>/unsuspend")
class AdminSellerUnsuspend(MethodView):
    @login_required
    @require_permission(Permission.SELLER_SUSPEND)
    @bp.arguments(AdminReasonSchema)
    @bp.response(200, AdminSellerDetailSchema)
    def post(self, data, seller_id):
        """Reactivate a suspended shop."""
        try:
            return AdminSellerService.unsuspend_seller(
                current_user, seller_id, data.get("reason")
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/sellers/<int:seller_id>/market-verification")
class AdminSellerMarketReview(MethodView):
    @login_required
    @require_permission(Permission.SELLER_MARKET_REVIEW)
    @bp.arguments(AdminSellerMarketReviewSchema)
    @bp.response(200, AdminSellerDetailSchema)
    def post(self, data, seller_id):
        """Confirm or override a shop's market-verification status."""
        try:
            return AdminSellerService.review_market_verification(
                current_user, seller_id, data["status"], data.get("reason")
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/sellers/<int:seller_id>/payout")
class AdminSellerPayout(MethodView):
    @login_required
    @require_permission(Permission.SELLER_EDIT_PAYOUT)
    @bp.arguments(AdminSellerPayoutEditSchema)
    @bp.response(200, AdminSellerDetailSchema)
    def patch(self, data, seller_id):
        """Edit/verify a shop's payout bank details."""
        try:
            return AdminSellerService.edit_payout(current_user, seller_id, data)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/sellers/<int:seller_id>/feature")
class AdminSellerFeature(MethodView):
    @login_required
    @require_permission(Permission.SELLER_FEATURE)
    @bp.arguments(AdminReasonSchema)
    @bp.response(200, AdminSellerDetailSchema)
    def post(self, data, seller_id):
        """Feature (promote) a shop."""
        try:
            return AdminSellerService.set_featured(
                current_user, seller_id, True, data.get("reason")
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/sellers/<int:seller_id>/unfeature")
class AdminSellerUnfeature(MethodView):
    @login_required
    @require_permission(Permission.SELLER_FEATURE)
    @bp.arguments(AdminReasonSchema)
    @bp.response(200, AdminSellerDetailSchema)
    def post(self, data, seller_id):
        """Remove a shop from featured."""
        try:
            return AdminSellerService.set_featured(
                current_user, seller_id, False, data.get("reason")
            )
        except APIError as e:
            abort(e.status_code, message=e.message)
