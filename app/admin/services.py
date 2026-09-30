"""Admin-side services.

- AdminAuditService: the audit recorder every admin action writes through.
- AdminUserService: §1 user management (view, suspend/ban, verification,
  force-logout, profile correction, role toggling).
- AdminSellerService: §2 seller verification & shop (queue, verify/reject,
  suspend, market-verification review, payout edit, feature toggle).
"""

from typing import Any, Optional

from sqlalchemy import or_

from app.libs.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.libs.session import read_scope, session_scope

from .models import AdminAuditLog
from .permissions import _role_of, is_super_admin


def _client_ip() -> Optional[str]:
    """Best-effort caller IP, or None outside a request context.

    Reads X-Forwarded-For first (the app runs behind a proxy in production)
    and falls back to the socket peer. Never raises: an audit row without an
    IP is fine, a failed audit write is not.
    """
    try:
        from flask import request

        fwd = request.headers.get("X-Forwarded-For")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.remote_addr
    except Exception:
        return None


class AdminAuditService:
    @staticmethod
    def record(
        session,
        actor,
        action: str,
        *,
        target_type: Optional[str] = None,
        target_id: Optional[Any] = None,
        reason: Optional[str] = None,
        before: Optional[dict] = None,
        after: Optional[dict] = None,
        ip_address: Optional[str] = None,
    ) -> AdminAuditLog:
        """Write one audit row on the caller's session (not a new one).

        Takes the live ``session`` so the row commits in the same transaction
        as the action it records -- an action and its audit entry are atomic.
        ``actor`` is the acting User; ``target_id`` is coerced to str so
        integer PKs (Seller.id) and string PKs (User.id) both work.
        """
        entry = AdminAuditLog(
            actor_id=getattr(actor, "id", None),
            actor_role=(_role_of(actor).value if _role_of(actor) else None),
            action=action,
            target_type=target_type,
            target_id=(str(target_id) if target_id is not None else None),
            reason=reason,
            before=before,
            after=after,
            ip_address=ip_address if ip_address is not None else _client_ip(),
        )
        session.add(entry)
        return entry


def _iso(dt):
    return dt.isoformat() if dt else None


def _account_status(user) -> str:
    """A single derived label for the account's admin/lifecycle state.

    Ordered by severity so the strongest state wins when several are set at
    once (a banned user is reported banned even if also self-deactivated)."""
    if user.deleted_at:
        return "deleted"
    if user.banned_at:
        return "banned"
    if user.suspended_at:
        return "suspended"
    if not user.is_active:
        return "deactivated"
    return "active"


class AdminUserService:
    """§1 user management. Every mutation records an audit row on the same
    transaction and returns the refreshed user detail."""

    STATUSES = ("active", "suspended", "banned", "deactivated", "deleted")
    ROLES = ("buyer", "seller", "admin", "staff")

    # --- serialisers ----------------------------------------------------
    @staticmethod
    def _list_item(u) -> dict:
        return {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "phone_number": u.phone_number,
            "profile_picture": u.profile_picture,
            "is_buyer": bool(u.is_buyer),
            "is_seller": bool(u.is_seller),
            "is_admin": bool(u.is_admin),
            "admin_role": u.admin_role,
            "email_verified": bool(u.email_verified),
            "status": _account_status(u),
            "created_at": _iso(u.created_at),
            "last_login_at": _iso(u.last_login_at),
        }

    @staticmethod
    def _detail(u) -> dict:
        data = AdminUserService._list_item(u)
        data.update(
            {
                "is_active": bool(u.is_active),
                "suspension_reason": u.suspension_reason,
                "ban_reason": u.ban_reason,
                "suspended_at": _iso(u.suspended_at),
                "banned_at": _iso(u.banned_at),
                "deactivated_at": _iso(u.deactivated_at),
                "deleted_at": _iso(u.deleted_at),
                "buyer": None,
                "seller": None,
            }
        )
        buyer = u.buyer_account
        if buyer:
            data["buyer"] = {
                "id": buyer.id,
                "buyername": buyer.buyername,
                "is_active": bool(buyer.is_active),
                "refund_preference": buyer.refund_preference,
            }
        seller = u.seller_account
        if seller:
            data["seller"] = {
                "id": seller.id,
                "shop_name": seller.shop_name,
                "shop_slug": seller.shop_slug,
                "is_active": bool(seller.is_active),
                "verification_status": (
                    seller.verification_status.value
                    if seller.verification_status
                    else None
                ),
                "market_verification_status": (
                    seller.market_verification_status.value
                    if seller.market_verification_status
                    else None
                ),
            }
        return data

    # --- guards ---------------------------------------------------------
    @staticmethod
    def _load(session, user_id):
        from app.users.models import User

        user = session.query(User).get(user_id)
        if not user:
            raise NotFoundError("User not found")
        return user

    @staticmethod
    def _guard_mutation(actor, target):
        """Refuse actions that a staff member should not be able to take.

        - Never act on your own account (an admin cannot lock themselves out).
        - Only a super_admin may act on another admin/super_admin, so a
          scoped staff member cannot suspend or ban the people above them.
        """
        if getattr(actor, "id", None) == target.id:
            raise ForbiddenError("You cannot perform this action on your own account")
        target_is_privileged = bool(target.is_admin) or target.admin_role
        if target_is_privileged and not is_super_admin(actor):
            raise ForbiddenError("Only a super admin may action an admin account")

    # --- reads ----------------------------------------------------------
    @staticmethod
    def list_users(
        q: Optional[str] = None,
        role: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        from app.users.models import User

        page = max(1, int(page or 1))
        per_page = min(100, max(1, int(per_page or 20)))

        with read_scope() as session:
            query = session.query(User)

            if q:
                like = f"%{q.strip()}%"
                query = query.filter(
                    or_(
                        User.email.ilike(like),
                        User.username.ilike(like),
                        User.id.ilike(like),
                        User.phone_number.ilike(like),
                    )
                )

            if role == "buyer":
                query = query.filter(User.is_buyer.is_(True))
            elif role == "seller":
                query = query.filter(User.is_seller.is_(True))
            elif role == "admin":
                query = query.filter(User.is_admin.is_(True))
            elif role == "staff":
                query = query.filter(User.admin_role.isnot(None))

            if status == "active":
                query = query.filter(
                    User.deleted_at.is_(None),
                    User.banned_at.is_(None),
                    User.suspended_at.is_(None),
                    User.is_active.is_(True),
                )
            elif status == "suspended":
                query = query.filter(User.suspended_at.isnot(None))
            elif status == "banned":
                query = query.filter(User.banned_at.isnot(None))
            elif status == "deactivated":
                query = query.filter(
                    User.is_active.is_(False),
                    User.suspended_at.is_(None),
                    User.banned_at.is_(None),
                    User.deleted_at.is_(None),
                )
            elif status == "deleted":
                query = query.filter(User.deleted_at.isnot(None))

            total = query.order_by(None).count()
            rows = (
                query.order_by(User.created_at.desc())
                .limit(per_page)
                .offset((page - 1) * per_page)
                .all()
            )
            items = [AdminUserService._list_item(u) for u in rows]

        from math import ceil

        return {
            "items": items,
            "page": page,
            "per_page": per_page,
            "total_items": total,
            "total_pages": ceil(total / per_page) if total else 0,
        }

    @staticmethod
    def get_user(user_id: str) -> dict:
        with read_scope() as session:
            return AdminUserService._detail(AdminUserService._load(session, user_id))

    # --- mutations ------------------------------------------------------
    @staticmethod
    def _require_not_deleted(user):
        if user.deleted_at:
            raise ValidationError("Cannot action a deleted account")

    @staticmethod
    def suspend_user(actor, user_id, reason=None) -> dict:
        with session_scope() as session:
            user = AdminUserService._load(session, user_id)
            AdminUserService._require_not_deleted(user)
            AdminUserService._guard_mutation(actor, user)
            before = {"status": _account_status(user)}
            user.suspend(reason)
            AdminAuditService.record(
                session,
                actor,
                "user.suspend",
                target_type="user",
                target_id=user_id,
                reason=reason,
                before=before,
                after={"status": _account_status(user)},
            )
            return AdminUserService._detail(user)

    @staticmethod
    def reinstate_user(actor, user_id, reason=None) -> dict:
        with session_scope() as session:
            user = AdminUserService._load(session, user_id)
            before = {"status": _account_status(user)}
            user.unsuspend()
            AdminAuditService.record(
                session,
                actor,
                "user.reinstate",
                target_type="user",
                target_id=user_id,
                reason=reason,
                before=before,
                after={"status": _account_status(user)},
            )
            return AdminUserService._detail(user)

    @staticmethod
    def ban_user(actor, user_id, reason=None) -> dict:
        with session_scope() as session:
            user = AdminUserService._load(session, user_id)
            AdminUserService._require_not_deleted(user)
            AdminUserService._guard_mutation(actor, user)
            before = {"status": _account_status(user)}
            user.ban(reason)
            AdminAuditService.record(
                session,
                actor,
                "user.ban",
                target_type="user",
                target_id=user_id,
                reason=reason,
                before=before,
                after={"status": _account_status(user)},
            )
            return AdminUserService._detail(user)

    @staticmethod
    def unban_user(actor, user_id, reason=None) -> dict:
        with session_scope() as session:
            user = AdminUserService._load(session, user_id)
            before = {"status": _account_status(user)}
            user.unban()
            AdminAuditService.record(
                session,
                actor,
                "user.unban",
                target_type="user",
                target_id=user_id,
                reason=reason,
                before=before,
                after={"status": _account_status(user)},
            )
            return AdminUserService._detail(user)

    @staticmethod
    def force_verify_email(actor, user_id) -> dict:
        with session_scope() as session:
            user = AdminUserService._load(session, user_id)
            AdminUserService._require_not_deleted(user)
            before = {"email_verified": bool(user.email_verified)}
            user.email_verified = True
            AdminAuditService.record(
                session,
                actor,
                "user.verify_email",
                target_type="user",
                target_id=user_id,
                before=before,
                after={"email_verified": True},
            )
            return AdminUserService._detail(user)

    @staticmethod
    def resend_verification(actor, user_id) -> dict:
        # Validate first, capture the email, then send outside our transaction:
        # AuthService.send_email_verification opens its own session_scope, so
        # nesting it inside one here would commit/rollback our audit with it.
        with read_scope() as session:
            user = AdminUserService._load(session, user_id)
            AdminUserService._require_not_deleted(user)
            if user.email_verified:
                raise ValidationError("Email already verified")
            email = user.email

        from app.users.services import AuthService

        AuthService.send_email_verification(email)  # may raise AuthError

        with session_scope() as session:
            AdminAuditService.record(
                session,
                actor,
                "user.resend_verification",
                target_type="user",
                target_id=user_id,
            )
        return {"sent": True, "email": email}

    @staticmethod
    def force_logout(actor, user_id, reason=None) -> dict:
        with session_scope() as session:
            user = AdminUserService._load(session, user_id)
            AdminUserService._require_not_deleted(user)
            user.revoke_tokens()
            AdminAuditService.record(
                session,
                actor,
                "user.force_logout",
                target_type="user",
                target_id=user_id,
                reason=reason,
                after={"tokens_valid_from": _iso(user.tokens_valid_from)},
            )
            return AdminUserService._detail(user)

    EDITABLE_FIELDS = ("phone_number", "username", "profile_picture")

    @staticmethod
    def edit_profile(actor, user_id, changes: dict) -> dict:
        from app.users.models import User

        changes = {
            k: v
            for k, v in (changes or {}).items()
            if k in AdminUserService.EDITABLE_FIELDS
        }
        if not changes:
            raise ValidationError("No editable fields supplied")

        with session_scope() as session:
            user = AdminUserService._load(session, user_id)
            AdminUserService._require_not_deleted(user)

            if "username" in changes and changes["username"] != user.username:
                clash = (
                    session.query(User)
                    .filter(User.username == changes["username"], User.id != user.id)
                    .first()
                )
                if clash:
                    raise ConflictError("Username already taken")

            before = {k: getattr(user, k) for k in changes}
            for k, v in changes.items():
                setattr(user, k, v)
            AdminAuditService.record(
                session,
                actor,
                "user.edit",
                target_type="user",
                target_id=user_id,
                before=before,
                after=changes,
            )
            return AdminUserService._detail(user)

    @staticmethod
    def manage_roles(actor, user_id, is_buyer=None, is_seller=None) -> dict:
        if is_buyer is None and is_seller is None:
            raise ValidationError("Specify is_buyer and/or is_seller")

        with session_scope() as session:
            user = AdminUserService._load(session, user_id)
            AdminUserService._require_not_deleted(user)
            before = {
                "is_buyer": bool(user.is_buyer),
                "is_seller": bool(user.is_seller),
            }

            if is_buyer is not None:
                if is_buyer and not user.buyer_account:
                    raise ValidationError(
                        "User has no buyer account to enable; it must be created "
                        "through onboarding first"
                    )
                user.is_buyer = bool(is_buyer)
                if user.buyer_account:
                    (
                        user.buyer_account.activate()
                        if is_buyer
                        else user.buyer_account.deactivate()
                    )

            if is_seller is not None:
                if is_seller and not user.seller_account:
                    raise ValidationError(
                        "User has no seller account to enable; it must be created "
                        "through onboarding first"
                    )
                user.is_seller = bool(is_seller)
                if user.seller_account:
                    (
                        user.seller_account.activate()
                        if is_seller
                        else user.seller_account.deactivate()
                    )

            after = {"is_buyer": bool(user.is_buyer), "is_seller": bool(user.is_seller)}
            AdminAuditService.record(
                session,
                actor,
                "user.manage_roles",
                target_type="user",
                target_id=user_id,
                before=before,
                after=after,
            )
            # The user's cached current_role may now point at a disabled role;
            # drop it so the next login recomputes rather than trusting stale
            # cache. Best-effort: a cache miss just recomputes anyway.
            try:
                from external.redis import redis_client
                from app.users.models import CURRENT_ROLE_CACHE_KEY

                redis_client.delete(CURRENT_ROLE_CACHE_KEY.format(user_id=user.id))
            except Exception:
                pass
            return AdminUserService._detail(user)
