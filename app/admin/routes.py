"""Admin API surface, mounted at /api/v1/admin.

Increment 1 establishes the module and the RBAC/audit foundations; §1 user
management and §2 seller verification land on this same blueprint in the
following increments.
"""

from flask.views import MethodView
from flask_login import current_user
from flask_smorest import Blueprint, abort

from app.libs.decorators import login_required, require_permission, staff_required
from app.libs.errors import APIError

from .permissions import Permission, is_super_admin, permissions_for
from .schemas import (
    AdminMeSchema,
    AdminReasonSchema,
    AdminResendVerificationResponseSchema,
    AdminUserDetailSchema,
    AdminUserEditSchema,
    AdminUserListQuerySchema,
    AdminUserListResponseSchema,
    AdminUserRolesSchema,
)
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
        return {
            "user_id": current_user.id,
            "email": current_user.email,
            "is_admin": bool(current_user.is_admin),
            "is_super_admin": is_super_admin(current_user),
            "admin_role": current_user.admin_role,
            "permissions": sorted(permissions_for(current_user)),
        }


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
