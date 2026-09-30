"""Admin RBAC: staff roles and the permission matrix.

Lightweight by design (ADMIN_MILESTONE_1_PLAN.md): a single ``User.admin_role``
string plus the code-defined matrix below, rather than RBAC tables. That keeps
"who can do what" reviewable in one place and versioned with the code that
enforces it, and matches how the rest of the codebase gates rare, powerful
capabilities -- a flag set directly in the DB, no self-serve path.

``is_admin`` remains the master gate: an ``is_admin`` user (or the
``super_admin`` role) holds every permission and is never enumerated in the
matrix. Every other role holds exactly the permissions listed for it.
"""

from enum import Enum


class AdminRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    SUPPORT = "support"
    FINANCE = "finance"
    MODERATION = "moderation"
    LOGISTICS = "logistics"
    CATALOG = "catalog"


class Permission:
    """Namespaced ``<domain>.<action>`` permission strings.

    Plain strings, not an enum: a new endpoint introduces its permission here
    and adds it to the relevant role(s) below -- the matrix stays the one
    source of truth without a second registry to keep in sync.
    """

    # Users (§1)
    USER_VIEW = "user.view"
    USER_SUSPEND = "user.suspend"
    USER_BAN = "user.ban"
    USER_EDIT = "user.edit"
    USER_VERIFY_EMAIL = "user.verify_email"
    USER_FORCE_LOGOUT = "user.force_logout"
    USER_MANAGE_ROLES = "user.manage_roles"

    # Sellers (§2)
    SELLER_VIEW = "seller.view"
    SELLER_VERIFY = "seller.verify"
    SELLER_SUSPEND = "seller.suspend"
    SELLER_EDIT_PAYOUT = "seller.edit_payout"
    SELLER_FEATURE = "seller.feature"
    SELLER_MARKET_REVIEW = "seller.market_review"


def all_permissions() -> set:
    """Every permission defined on :class:`Permission` (the super_admin set)."""
    return {
        value
        for key, value in vars(Permission).items()
        if not key.startswith("_") and isinstance(value, str)
    }


# Role -> permissions. SUPER_ADMIN is handled specially (all permissions) and
# is deliberately absent here so the "everything" grant lives in exactly one
# place (`is_super_admin`), not as a list that can drift from `all_permissions`.
ROLE_PERMISSIONS = {
    AdminRole.SUPPORT: {
        Permission.USER_VIEW,
        Permission.USER_EDIT,
        Permission.USER_VERIFY_EMAIL,
        Permission.USER_FORCE_LOGOUT,
        Permission.SELLER_VIEW,
    },
    AdminRole.MODERATION: {
        Permission.USER_VIEW,
        Permission.USER_SUSPEND,
        Permission.USER_BAN,
        Permission.SELLER_VIEW,
        Permission.SELLER_SUSPEND,
    },
    AdminRole.FINANCE: {
        Permission.USER_VIEW,
        Permission.SELLER_VIEW,
        Permission.SELLER_EDIT_PAYOUT,
    },
    AdminRole.CATALOG: {
        Permission.USER_VIEW,
        Permission.SELLER_VIEW,
        Permission.SELLER_VERIFY,
        Permission.SELLER_SUSPEND,
        Permission.SELLER_FEATURE,
        Permission.SELLER_MARKET_REVIEW,
    },
    AdminRole.LOGISTICS: {
        Permission.USER_VIEW,
        Permission.SELLER_VIEW,
        Permission.SELLER_MARKET_REVIEW,
    },
}


def _role_of(user):
    """The user's :class:`AdminRole`, or None if unset/unrecognised."""
    raw = getattr(user, "admin_role", None)
    if not raw:
        return None
    try:
        return AdminRole(raw)
    except ValueError:
        # A role string in the DB that no longer maps to a known role grants
        # nothing, rather than erroring -- fail closed.
        return None


def is_super_admin(user) -> bool:
    return (
        bool(getattr(user, "is_admin", False))
        or _role_of(user) is AdminRole.SUPER_ADMIN
    )


def is_staff(user) -> bool:
    """Any admin standing at all: legacy ``is_admin`` or a recognised role."""
    return bool(getattr(user, "is_admin", False)) or _role_of(user) is not None


def permissions_for(user) -> set:
    """The full permission set a user holds. super_admin / is_admin => all."""
    if is_super_admin(user):
        return all_permissions()
    role = _role_of(user)
    if role is None:
        return set()
    return set(ROLE_PERMISSIONS.get(role, set()))


def has_permission(user, permission: str) -> bool:
    if is_super_admin(user):
        return True
    return permission in permissions_for(user)
