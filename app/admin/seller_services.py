"""§2 seller verification & shop management.

Keyed by seller id (the integer Seller PK). Every mutation writes an audit row
on the same transaction and returns the refreshed seller detail. Reuses the
audit recorder and shared helpers from app.admin.services.
"""

from math import ceil
from typing import Optional

from sqlalchemy import or_

from app.libs.errors import NotFoundError, ValidationError
from app.libs.session import read_scope, session_scope

from .services import AdminAuditService, _iso


class AdminSellerService:
    VERIFICATION_STATUSES = (
        "unverified",
        "pending",
        "verified",
        "rejected",
        "suspended",
    )
    MARKET_STATUSES = ("unverified", "verified", "flagged")

    # --- serialisers ----------------------------------------------------
    @staticmethod
    def _enum_value(v):
        return v.value if v is not None else None

    @staticmethod
    def _list_item(s) -> dict:
        user = s.user
        return {
            "id": s.id,
            "user_id": s.user_id,
            "shop_name": s.shop_name,
            "shop_slug": s.shop_slug,
            "is_active": bool(s.is_active),
            "is_featured": bool(s.is_featured),
            "verification_status": AdminSellerService._enum_value(
                s.verification_status
            ),
            "market_verification_status": AdminSellerService._enum_value(
                s.market_verification_status
            ),
            "email": user.email if user else None,
            "username": user.username if user else None,
            "total_rating": s.total_rating,
            "total_raters": s.total_raters,
            "created_at": _iso(s.created_at),
        }

    @staticmethod
    def _detail(s) -> dict:
        data = AdminSellerService._list_item(s)
        data.update(
            {
                "description": s.description,
                "banner_url": s.banner_url,
                "policies": s.policies,
                "verification_note": s.verification_note,
                "payout": {
                    "bank_code": s.payout_bank_code,
                    "account_number": s.payout_account_number,
                    "account_name": s.payout_account_name,
                    "paystack_subaccount_code": s.paystack_subaccount_code,
                },
                "market": {
                    "market_id": s.market_id,
                    "shop_address": s.shop_address,
                    "shop_latitude": s.shop_latitude,
                    "shop_longitude": s.shop_longitude,
                },
            }
        )
        return data

    # --- helpers --------------------------------------------------------
    @staticmethod
    def _load(session, seller_id):
        from app.users.models import Seller

        seller = session.query(Seller).get(seller_id)
        if not seller:
            raise NotFoundError("Seller not found")
        return seller

    # --- reads ----------------------------------------------------------
    @staticmethod
    def list_sellers(
        q: Optional[str] = None,
        verification_status: Optional[str] = None,
        market_status: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_featured: Optional[bool] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        from app.users.models import (
            MarketVerificationStatus,
            Seller,
            SellerVerificationStatus,
            User,
        )

        page = max(1, int(page or 1))
        per_page = min(100, max(1, int(per_page or 20)))

        with read_scope() as session:
            query = session.query(Seller).join(User, Seller.user_id == User.id)

            if q:
                like = f"%{q.strip()}%"
                query = query.filter(
                    or_(
                        Seller.shop_name.ilike(like),
                        Seller.shop_slug.ilike(like),
                        User.email.ilike(like),
                        User.username.ilike(like),
                    )
                )
            if verification_status:
                query = query.filter(
                    Seller.verification_status
                    == SellerVerificationStatus(verification_status)
                )
            if market_status:
                query = query.filter(
                    Seller.market_verification_status
                    == MarketVerificationStatus(market_status)
                )
            if is_active is not None:
                query = query.filter(Seller.is_active.is_(bool(is_active)))
            if is_featured is not None:
                query = query.filter(Seller.is_featured.is_(bool(is_featured)))

            total = query.order_by(None).count()
            rows = (
                query.order_by(Seller.created_at.desc())
                .limit(per_page)
                .offset((page - 1) * per_page)
                .all()
            )
            items = [AdminSellerService._list_item(s) for s in rows]

        return {
            "items": items,
            "page": page,
            "per_page": per_page,
            "total_items": total,
            "total_pages": ceil(total / per_page) if total else 0,
        }

    @staticmethod
    def get_seller(seller_id: int) -> dict:
        with read_scope() as session:
            return AdminSellerService._detail(
                AdminSellerService._load(session, seller_id)
            )

    # --- mutations ------------------------------------------------------
    @staticmethod
    def verify_seller(actor, seller_id, note=None) -> dict:
        from app.users.models import SellerVerificationStatus

        with session_scope() as session:
            seller = AdminSellerService._load(session, seller_id)
            before = {
                "verification_status": AdminSellerService._enum_value(
                    seller.verification_status
                )
            }
            seller.verification_status = SellerVerificationStatus.VERIFIED
            seller.verification_note = note
            AdminAuditService.record(
                session,
                actor,
                "seller.verify",
                target_type="seller",
                target_id=seller_id,
                reason=note,
                before=before,
                after={"verification_status": "verified"},
            )
            return AdminSellerService._detail(seller)

    @staticmethod
    def reject_seller(actor, seller_id, reason) -> dict:
        from app.users.models import SellerVerificationStatus

        if not reason:
            raise ValidationError("A reason is required to reject verification")
        with session_scope() as session:
            seller = AdminSellerService._load(session, seller_id)
            before = {
                "verification_status": AdminSellerService._enum_value(
                    seller.verification_status
                )
            }
            seller.verification_status = SellerVerificationStatus.REJECTED
            seller.verification_note = reason
            AdminAuditService.record(
                session,
                actor,
                "seller.reject",
                target_type="seller",
                target_id=seller_id,
                reason=reason,
                before=before,
                after={"verification_status": "rejected"},
            )
            return AdminSellerService._detail(seller)

    @staticmethod
    def suspend_seller(actor, seller_id, reason=None) -> dict:
        """Stop a shop selling. is_active is the real gate (seller_required,
        discovery and eligibility filters all key off it); verification_status
        is left untouched so KYC standing survives the suspension."""
        with session_scope() as session:
            seller = AdminSellerService._load(session, seller_id)
            before = {"is_active": bool(seller.is_active)}
            seller.deactivate()
            AdminAuditService.record(
                session,
                actor,
                "seller.suspend",
                target_type="seller",
                target_id=seller_id,
                reason=reason,
                before=before,
                after={"is_active": False},
            )
            return AdminSellerService._detail(seller)

    @staticmethod
    def unsuspend_seller(actor, seller_id, reason=None) -> dict:
        with session_scope() as session:
            seller = AdminSellerService._load(session, seller_id)
            before = {"is_active": bool(seller.is_active)}
            seller.activate()
            AdminAuditService.record(
                session,
                actor,
                "seller.unsuspend",
                target_type="seller",
                target_id=seller_id,
                reason=reason,
                before=before,
                after={"is_active": True},
            )
            return AdminSellerService._detail(seller)

    @staticmethod
    def review_market_verification(actor, seller_id, status, reason=None) -> dict:
        from app.users.models import MarketVerificationStatus

        try:
            new_status = MarketVerificationStatus(status)
        except ValueError:
            raise ValidationError("Unknown market verification status")
        with session_scope() as session:
            seller = AdminSellerService._load(session, seller_id)
            before = {
                "market_verification_status": AdminSellerService._enum_value(
                    seller.market_verification_status
                )
            }
            seller.market_verification_status = new_status
            AdminAuditService.record(
                session,
                actor,
                "seller.market_review",
                target_type="seller",
                target_id=seller_id,
                reason=reason,
                before=before,
                after={"market_verification_status": new_status.value},
            )
            return AdminSellerService._detail(seller)

    PAYOUT_FIELDS = (
        "payout_bank_code",
        "payout_account_number",
        "payout_account_name",
    )

    @staticmethod
    def edit_payout(actor, seller_id, changes: dict) -> dict:
        changes = {
            k: v
            for k, v in (changes or {}).items()
            if k in AdminSellerService.PAYOUT_FIELDS
        }
        if not changes:
            raise ValidationError("No payout fields supplied")
        with session_scope() as session:
            seller = AdminSellerService._load(session, seller_id)
            before = {k: getattr(seller, k) for k in changes}
            for k, v in changes.items():
                setattr(seller, k, v)
            AdminAuditService.record(
                session,
                actor,
                "seller.edit_payout",
                target_type="seller",
                target_id=seller_id,
                before=before,
                after=changes,
            )
            return AdminSellerService._detail(seller)

    @staticmethod
    def set_featured(actor, seller_id, featured: bool, reason=None) -> dict:
        with session_scope() as session:
            seller = AdminSellerService._load(session, seller_id)
            before = {"is_featured": bool(seller.is_featured)}
            seller.is_featured = bool(featured)
            AdminAuditService.record(
                session,
                actor,
                "seller.feature" if featured else "seller.unfeature",
                target_type="seller",
                target_id=seller_id,
                reason=reason,
                before=before,
                after={"is_featured": bool(featured)},
            )
            return AdminSellerService._detail(seller)
