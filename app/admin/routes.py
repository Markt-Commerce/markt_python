"""Admin API surface, mounted at /api/v1/admin.

Increment 1 establishes the module and the RBAC/audit foundations; §1 user
management and §2 seller verification land on this same blueprint in the
following increments.
"""

from flask.views import MethodView
from flask_login import current_user
from flask_smorest import Blueprint

from app.libs.decorators import login_required, staff_required

from .permissions import is_super_admin, permissions_for
from .schemas import AdminMeSchema

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
