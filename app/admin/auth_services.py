"""Staff sign-in and sign-out for the web admin console.

The customer login (POST /users/login) is built around buyer/seller accounts:
it refuses anyone without an active buyer or seller profile and treats an
unverified email as an unfinished signup (sending a code as a side effect).
Neither fits staff, so the console signs in here instead. Same credentials,
same bearer token format and the same request loader -- only the eligibility
rules differ: the account must be staff, and must not be blocked.

Sign-out bumps ``tokens_valid_from``. Bearer tokens are stateless signed ids,
so they cannot be revoked one at a time without a server-side store; the
"valid since" stamp invalidates every token the staff member holds in one
write, which is the same mechanism admin force-logout already uses.
"""

from datetime import datetime

from app.libs.auth_tokens import generate_auth_token
from app.libs.errors import AuthError, ForbiddenError
from app.libs.session import session_scope

from .permissions import is_staff, is_super_admin, permissions_for
from .services import AdminAuditService


def admin_me_payload(user) -> dict:
    """The /admin/me body. Shared with login so the console can render the
    shell straight from the sign-in response."""
    return {
        "user_id": user.id,
        "email": user.email,
        "is_admin": bool(user.is_admin),
        "is_super_admin": is_super_admin(user),
        "admin_role": user.admin_role,
        "permissions": sorted(permissions_for(user)),
    }


class AdminAuthService:
    @staticmethod
    def login(email: str, password: str) -> dict:
        from app.users.models import User

        with session_scope() as session:
            user = session.query(User).filter(User.email == email).first()
            # Unknown, deleted and wrong-password all read the same, as on the
            # customer login, so the endpoint does not confirm which addresses
            # have accounts.
            if not user or user.deleted_at or not user.check_password(password):
                raise AuthError("Invalid credentials")

            # Only checked after the password, so this reveals nothing to
            # someone who does not already hold the account's credentials.
            if not is_staff(user):
                raise ForbiddenError("This account does not have admin access")

            if user.banned_at:
                raise AuthError("Account is banned")
            if user.suspended_at:
                raise AuthError("Account is suspended")
            if not user.is_active:
                raise AuthError("Account is deactivated")

            # Staff accounts are provisioned by hand, so an unverified one is
            # a setup gap for a super admin to fix (POST .../verify-email),
            # not a signup to resume. No code is sent from here.
            if not user.email_verified:
                raise ForbiddenError(
                    "This account's email address is not verified. "
                    "Ask a super admin to verify it."
                )

            user.last_login_at = datetime.utcnow()
            AdminAuditService.record(
                session,
                user,
                "admin.login",
                target_type="user",
                target_id=user.id,
            )
            payload = admin_me_payload(user)
            payload["access_token"] = generate_auth_token(user.id)
            return payload

    @staticmethod
    def logout(user_id: str) -> None:
        """Revoke every bearer token the staff member holds."""
        from app.users.models import User

        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not user:
                return
            user.revoke_tokens()
            AdminAuditService.record(
                session,
                user,
                "admin.logout",
                target_type="user",
                target_id=user.id,
            )
