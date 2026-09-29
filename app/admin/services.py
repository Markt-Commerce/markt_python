"""Admin-side services. Increment 1 provides only the audit recorder;
user/seller actions (Increments 2-3) call into it."""

from typing import Any, Optional

from .models import AdminAuditLog
from .permissions import _role_of


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
