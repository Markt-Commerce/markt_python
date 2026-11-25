"""Markt Business verification review.

Keyed by the business owner's user id (one business profile per user).
Mirrors seller verification: every mutation writes an audit row on the same
transaction and returns the refreshed detail. Registration never verifies a
business; only these actions move it past PENDING.
"""

from math import ceil
from typing import Optional

from sqlalchemy import or_

from app.libs.errors import NotFoundError, ValidationError
from app.libs.session import read_scope, session_scope

from .services import AdminAuditService, _iso


class AdminBusinessService:
    VERIFICATION_STATUSES = ("unverified", "pending", "verified", "rejected")

    @staticmethod
    def _detail(p) -> dict:
        user = p.user
        return {
            "user_id": p.user_id,
            "name": p.name,
            "business_types": list(p.business_types or []),
            "industry": p.industry,
            "city": p.city,
            "state": p.state,
            "registration_number": p.registration_number,
            "contact_email": p.contact_email,
            "contact_phone": p.contact_phone,
            "website": p.website,
            "verification_status": p.verification_status.value
            if p.verification_status
            else None,
            "verification_note": p.verification_note,
            "is_business": bool(user.is_business) if user else False,
            "email": user.email if user else None,
            "username": user.username if user else None,
            "created_at": _iso(p.created_at),
            "updated_at": _iso(p.updated_at),
        }

    @staticmethod
    def _load(session, user_id):
        from app.business.models import BusinessProfile

        profile = session.query(BusinessProfile).filter_by(user_id=user_id).first()
        if not profile:
            raise NotFoundError("Business not found")
        return profile

    @staticmethod
    def list_businesses(
        q: Optional[str] = None,
        verification_status: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """The verification queue: filter by status, pending first by default."""
        from app.business.models import BusinessProfile, BusinessVerificationStatus
        from app.users.models import User

        per_page = max(1, min(per_page or 20, 100))
        page = max(1, page or 1)
        with read_scope() as session:
            query = session.query(BusinessProfile).join(
                User, BusinessProfile.user_id == User.id
            )
            if verification_status:
                query = query.filter(
                    BusinessProfile.verification_status
                    == BusinessVerificationStatus(verification_status)
                )
            if q:
                term = f"%{q}%"
                query = query.filter(
                    or_(
                        BusinessProfile.name.ilike(term),
                        BusinessProfile.registration_number.ilike(term),
                        User.email.ilike(term),
                        User.username.ilike(term),
                    )
                )
            total = query.count()
            items = (
                query.order_by(BusinessProfile.updated_at.desc())
                .limit(per_page)
                .offset((page - 1) * per_page)
                .all()
            )
            return {
                "items": [AdminBusinessService._detail(p) for p in items],
                "page": page,
                "per_page": per_page,
                "total_items": total,
                "total_pages": ceil(total / per_page) if total else 0,
            }

    @staticmethod
    def get_business(user_id: str) -> dict:
        with read_scope() as session:
            return AdminBusinessService._detail(
                AdminBusinessService._load(session, user_id)
            )

    @staticmethod
    def _set_status(actor, user_id, status, note, action) -> dict:
        with session_scope() as session:
            profile = AdminBusinessService._load(session, user_id)
            before = {"verification_status": profile.verification_status.value}
            profile.verification_status = status
            profile.verification_note = note
            AdminAuditService.record(
                session,
                actor,
                action,
                target_type="business",
                target_id=user_id,
                reason=note,
                before=before,
                after={"verification_status": status.value},
            )
            return AdminBusinessService._detail(profile)

    @staticmethod
    def verify_business(actor, user_id, note=None) -> dict:
        from app.business.models import BusinessVerificationStatus

        return AdminBusinessService._set_status(
            actor, user_id, BusinessVerificationStatus.VERIFIED, note, "business.verify"
        )

    @staticmethod
    def reject_business(actor, user_id, reason) -> dict:
        from app.business.models import BusinessVerificationStatus

        if not reason:
            raise ValidationError("A reason is required to reject verification")
        return AdminBusinessService._set_status(
            actor,
            user_id,
            BusinessVerificationStatus.REJECTED,
            reason,
            "business.reject",
        )

    @staticmethod
    def reset_business(actor, user_id, reason=None) -> dict:
        """Withdraw a verification (back to UNVERIFIED), e.g. the business
        changed hands or its details stopped checking out."""
        from app.business.models import BusinessVerificationStatus

        return AdminBusinessService._set_status(
            actor,
            user_id,
            BusinessVerificationStatus.UNVERIFIED,
            reason,
            "business.unverify",
        )
