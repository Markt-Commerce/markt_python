import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.libs.errors import ForbiddenError, NotFoundError, ValidationError
from app.libs.session import session_scope
from app.categories.models import ProductCategory
from app.products.models import Product, ProductStatus
from app.users.models import Seller, User

from .entitlements import EntitlementService
from .features import business_features
from .models import (
    BusinessListing,
    BusinessProfile,
    BusinessSubscription,
    BusinessSubscriptionPlan,
    BusinessSubscriptionStatus,
)

logger = logging.getLogger(__name__)


def _page(query, args: Dict[str, Any]) -> Dict[str, Any]:
    """Paginate without the generic Paginator's client-supplied filters and
    sort, which would let a caller filter on any column of these tables."""
    page = args.get("page", 1)
    per_page = args.get("per_page", 20)
    total = query.order_by(None).count()
    items = query.limit(per_page).offset((page - 1) * per_page).all()
    return {
        "items": items,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_items": total,
            "total_pages": -(-total // per_page) if total else 0,
        },
    }


def _require(feature: str):
    if not business_features().get(feature):
        raise ForbiddenError("This Markt Business feature is not available")


class BusinessService:
    # --- the signed-in user's business -------------------------------------

    @staticmethod
    def my_business(user_id: str) -> Dict[str, Any]:
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not user:
                raise NotFoundError("User not found")
            effective = EntitlementService.is_business(user)
            return {
                "is_business": effective,
                "business_tag": bool(user.is_business),
                "requires_subscription": bool(user.is_business) and not effective,
                "profile": user.business_profile,
            }

    @staticmethod
    def upsert_profile(user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create or update the business profile and set the is_business tag.

        Setting the tag is free. Whether it counts is the entitlement
        service's call, so with subscriptions on a user can still fill in
        their profile before they subscribe.
        """
        _require("registration_enabled")
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not user:
                raise NotFoundError("User not found")

            profile = user.business_profile
            if profile is None:
                # Through the relationship, not user_id=: user.business_profile
                # was already loaded as None above and would stay stale.
                profile = BusinessProfile(user=user)
                session.add(profile)
            for key, value in data.items():
                setattr(profile, key, value)
            user.is_business = True
            session.flush()
        return BusinessService.my_business(user_id)

    @staticmethod
    def disable_business(user_id: str) -> Dict[str, Any]:
        """Drop the tag. The profile is kept so turning it back on is one tap."""
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not user:
                raise NotFoundError("User not found")
            user.is_business = False
        return BusinessService.my_business(user_id)

    # --- public profiles and discovery -------------------------------------

    @staticmethod
    def get_public_profile(user_id: str) -> BusinessProfile:
        _require("enabled")
        with session_scope() as session:
            user = session.query(User).get(user_id)
            # A user who is not (or no longer) a business looks the same as
            # one who does not exist.
            if (
                not user
                or not user.is_active
                or user.deleted_at
                or not user.business_profile
                or not EntitlementService.is_business(user)
            ):
                raise NotFoundError("Business not found")
            return user.business_profile

    @staticmethod
    def discover(args: Dict[str, Any]) -> Dict[str, Any]:
        _require("discovery_enabled")
        with session_scope() as session:
            query = (
                session.query(BusinessProfile)
                .join(User, BusinessProfile.user_id == User.id)
                .options(joinedload(BusinessProfile.user))
                .filter(
                    EntitlementService.business_user_filter(User),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )
            if args.get("search"):
                term = f"%{args['search']}%"
                query = query.filter(
                    or_(
                        BusinessProfile.name.ilike(term),
                        BusinessProfile.description.ilike(term),
                    )
                )
            if args.get("business_type"):
                query = query.filter(
                    BusinessProfile.business_types.contains([args["business_type"]])
                )
            if args.get("industry"):
                query = query.filter(BusinessProfile.industry == args["industry"])
            if args.get("state"):
                query = query.filter(BusinessProfile.state.ilike(args["state"]))
            if args.get("city"):
                query = query.filter(BusinessProfile.city.ilike(args["city"]))
            if args.get("side") == "buys":
                query = query.filter(User.is_buyer.is_(True))
            elif args.get("side") == "sells":
                query = query.filter(User.is_seller.is_(True))

            query = query.order_by(BusinessProfile.updated_at.desc())
            return _page(query, args)


class BusinessListingService:
    @staticmethod
    def _owned_product(session, user_id: str, product_id: str) -> Product:
        product = session.query(Product).get(product_id)
        if not product or product.status == ProductStatus.DELETED:
            raise NotFoundError("Product not found")
        if not product.seller or product.seller.user_id != user_id:
            raise ForbiddenError("You can only edit your own products")
        return product

    @staticmethod
    def upsert_listing(
        user_id: str, product_id: str, data: Dict[str, Any]
    ) -> BusinessListing:
        _require("enabled")
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not EntitlementService.is_business(user):
                raise ForbiddenError("Set up a business profile to add B2B details")
            product = BusinessListingService._owned_product(
                session, user_id, product_id
            )
            listing = product.business_listing
            if listing is None:
                listing = BusinessListing(product_id=product.id)
                session.add(listing)
            for key, value in data.items():
                setattr(listing, key, value)
            # Default the listing's location to the business's own.
            profile = user.business_profile
            if profile:
                listing.city = listing.city or profile.city
                listing.state = listing.state or profile.state
            session.flush()
            return listing

    @staticmethod
    def remove_listing(user_id: str, product_id: str) -> None:
        """Stop offering a product as a B2B listing. The product itself stays."""
        with session_scope() as session:
            product = BusinessListingService._owned_product(
                session, user_id, product_id
            )
            if product.business_listing:
                session.delete(product.business_listing)

    @staticmethod
    def get_listing(product_id: str) -> BusinessListing:
        with session_scope() as session:
            listing = (
                session.query(BusinessListing).filter_by(product_id=product_id).first()
            )
            if not listing:
                raise NotFoundError("This product has no business listing")
            return listing

    @staticmethod
    def search(args: Dict[str, Any]) -> Dict[str, Any]:
        _require("discovery_enabled")
        with session_scope() as session:
            query = (
                session.query(Product)
                .join(BusinessListing, BusinessListing.product_id == Product.id)
                .join(Seller, Product.seller_id == Seller.id)
                .join(User, Seller.user_id == User.id)
                .options(
                    joinedload(Product.business_listing),
                    joinedload(Product.seller).joinedload(Seller.user),
                )
                .filter(
                    Product.status == ProductStatus.ACTIVE,
                    Seller.is_active.is_(True),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    EntitlementService.business_user_filter(User),
                )
            )
            if args.get("search"):
                term = f"%{args['search']}%"
                query = query.filter(
                    or_(Product.name.ilike(term), Product.description.ilike(term))
                )
            if args.get("category_id"):
                query = query.join(
                    ProductCategory, ProductCategory.product_id == Product.id
                ).filter(ProductCategory.category_id == args["category_id"])
            if args.get("unit"):
                query = query.filter(BusinessListing.unit == args["unit"])
            if args.get("state"):
                query = query.filter(BusinessListing.state.ilike(args["state"]))
            if args.get("city"):
                query = query.filter(BusinessListing.city.ilike(args["city"]))
            if args.get("min_available") is not None:
                query = query.filter(
                    BusinessListing.available_quantity >= args["min_available"]
                )
            if args.get("max_min_order") is not None:
                query = query.filter(
                    or_(
                        BusinessListing.min_order_quantity.is_(None),
                        BusinessListing.min_order_quantity <= args["max_min_order"],
                    )
                )
            if args.get("seller_user_id"):
                query = query.filter(User.id == args["seller_user_id"])

            query = query.order_by(BusinessListing.updated_at.desc())
            return _page(query, args)


class BusinessSubscriptionService:
    """Plans and subscriptions. Every read refuses while subscriptions are
    off, so nothing about them leaks into the UI."""

    @staticmethod
    def _require_enabled():
        if not business_features()["subscriptions_enabled"]:
            raise NotFoundError("Subscriptions are not available")

    @staticmethod
    def list_plans():
        BusinessSubscriptionService._require_enabled()
        with session_scope() as session:
            return (
                session.query(BusinessSubscriptionPlan)
                .filter_by(is_active=True)
                .order_by(BusinessSubscriptionPlan.sort_order)
                .all()
            )

    @staticmethod
    def current_subscription(user_id: str) -> Optional[BusinessSubscription]:
        BusinessSubscriptionService._require_enabled()
        with session_scope() as session:
            return (
                session.query(BusinessSubscription)
                .filter(
                    BusinessSubscription.user_id == user_id,
                    EntitlementService._active_clause(),
                )
                .order_by(BusinessSubscription.start_date.desc())
                .first()
            )

    @staticmethod
    def activate(
        user_id: str,
        plan_id: int,
        payment_reference: str,
        end_date: Optional[datetime] = None,
    ) -> BusinessSubscription:
        """Record a paid subscription. Called by the payment confirmation
        path once one exists; there is no public endpoint for it, because a
        subscription must never be granted on the client's word."""
        with session_scope() as session:
            existing = (
                session.query(BusinessSubscription)
                .filter_by(payment_reference=payment_reference)
                .first()
            )
            if existing:
                return existing  # idempotent on the payment reference
            plan = session.query(BusinessSubscriptionPlan).get(plan_id)
            if not plan or not plan.is_active:
                raise ValidationError("Unknown plan")
            now = datetime.utcnow()
            subscription = BusinessSubscription(
                user_id=user_id,
                plan_id=plan.id,
                status=BusinessSubscriptionStatus.ACTIVE,
                start_date=now,
                end_date=end_date,
                renewal_date=end_date,
                payment_reference=payment_reference,
            )
            session.add(subscription)
            session.flush()
            return subscription
