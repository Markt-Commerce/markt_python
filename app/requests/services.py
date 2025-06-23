# python imports
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from enum import Enum

# package imports
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy import and_, or_, func

# project imports
from external.redis import redis_client
from app.libs.session import session_scope
from app.libs.pagination import Paginator
from app.libs.errors import (
    NotFoundError,
    ValidationError,
    ConflictError,
    ForbiddenError,
)

# app imports
from .models import BuyerRequest, SellerOffer, RequestImage, RequestStatus
from app.users.models import User, Seller
from app.products.models import Product
from app.notifications.services import NotificationService
from app.notifications.models import NotificationType

logger = logging.getLogger(__name__)


class OfferStatus(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class BuyerRequestService:
    """Service for managing buyer requests with dual-role validation and status state machine"""

    # Status transition rules
    STATUS_TRANSITIONS = {
        RequestStatus.OPEN: [
            RequestStatus.FULFILLED,
            RequestStatus.CLOSED,
            RequestStatus.EXPIRED,
        ],
        RequestStatus.FULFILLED: [RequestStatus.CLOSED],
        RequestStatus.CLOSED: [],  # Terminal state
        RequestStatus.EXPIRED: [RequestStatus.CLOSED],  # Can be reopened
    }

    # Cache keys
    CACHE_KEYS = {
        "request": "request:{request_id}",
        "user_requests": "user:{user_id}:requests",
        "category_requests": "category:{category_id}:requests",
        "trending_requests": "trending:requests",
    }

    @staticmethod
    def create_request(user_id: str, data: Dict[str, Any]) -> BuyerRequest:
        """Create a new buyer request with dual-role validation"""
        with session_scope() as session:
            # Validate user has buyer account
            user = session.query(User).get(user_id)
            if not user or not user.is_buyer:
                raise ForbiddenError("Only buyers can create requests")

            # Validate request data
            if not data.get("title") or not data.get("description"):
                raise ValidationError("Title and description are required")

            # Set expiration date (default 30 days)
            expires_at = data.get("expires_at")
            if not expires_at:
                expires_at = datetime.utcnow() + timedelta(days=30)

            # Create request
            request = BuyerRequest(
                user_id=user_id,
                title=data["title"],
                description=data["description"],
                category_id=data.get("category_id"),
                budget=data.get("budget"),
                request_metadata=data.get("metadata", {}),
                expires_at=expires_at,
                status=RequestStatus.OPEN,
            )

            session.add(request)
            session.flush()

            # Handle images if provided
            if data.get("images"):
                for i, image_data in enumerate(data["images"]):
                    image = RequestImage(
                        request_id=request.id,
                        image_url=image_data["url"],
                        is_primary=(i == 0),  # First image is primary
                    )
                    session.add(image)

            # Cache invalidation
            BuyerRequestService._invalidate_user_cache(user_id)
            BuyerRequestService._invalidate_category_cache(data.get("category_id"))

            # Create notification for relevant sellers
            BuyerRequestService._notify_relevant_sellers(request)

            return request

    @staticmethod
    def get_request(request_id: str, user_id: Optional[str] = None) -> BuyerRequest:
        """Get request details with role-based access control"""
        # Try cache first
        cache_key = BuyerRequestService.CACHE_KEYS["request"].format(
            request_id=request_id
        )
        cached = redis_client.get(cache_key)
        if cached:
            return cached

        with session_scope() as session:
            request = (
                session.query(BuyerRequest)
                .options(
                    joinedload(BuyerRequest.user),
                    joinedload(BuyerRequest.category),
                    joinedload(BuyerRequest.images),
                    joinedload(BuyerRequest.offers).joinedload(SellerOffer.seller),
                )
                .get(request_id)
            )

            if not request:
                raise NotFoundError("Request not found")

            # Role-based access control
            if user_id:
                user = session.query(User).get(user_id)
                if user:
                    # Buyers can only see their own requests or public requests
                    if user.is_buyer and request.user_id != user_id:
                        # Check if request is still open and not expired
                        if (
                            request.status != RequestStatus.OPEN
                            or request.expires_at < datetime.utcnow()
                        ):
                            raise ForbiddenError("Access denied")

                    # Sellers can see all open requests
                    elif user.is_seller:
                        if request.status != RequestStatus.OPEN:
                            raise ForbiddenError(
                                "Request is no longer accepting offers"
                            )

            # Increment view count
            request.views += 1

            # Cache for 5 minutes
            redis_client.setex(cache_key, 300, request)

            return request

    @staticmethod
    def update_request_status(
        request_id: str, user_id: str, new_status: RequestStatus
    ) -> BuyerRequest:
        """Update request status with state machine validation"""
        with session_scope() as session:
            request = session.query(BuyerRequest).get(request_id)
            if not request:
                raise NotFoundError("Request not found")

            # Validate ownership
            if request.user_id != user_id:
                raise ForbiddenError("Only request owner can update status")

            # Validate status transition
            if new_status not in BuyerRequestService.STATUS_TRANSITIONS.get(
                request.status, []
            ):
                raise ValidationError(
                    f"Invalid status transition from {request.status} to {new_status}"
                )

            old_status = request.status
            request.status = new_status

            # Handle status-specific logic
            if new_status == RequestStatus.CLOSED:
                BuyerRequestService._handle_request_closure(request, session)
            elif new_status == RequestStatus.EXPIRED:
                BuyerRequestService._handle_request_expiration(request, session)

            # Cache invalidation
            BuyerRequestService._invalidate_request_cache(request_id)

            # Notify relevant parties
            BuyerRequestService._notify_status_change(request, old_status, new_status)

            return request

    @staticmethod
    def create_offer(
        seller_id: int, request_id: str, data: Dict[str, Any]
    ) -> SellerOffer:
        """Create seller offer with conflict resolution"""
        with session_scope() as session:
            # Validate seller exists and has seller account
            seller = session.query(Seller).get(seller_id)
            if not seller:
                raise NotFoundError("Seller not found")

            # Validate request is open
            request = session.query(BuyerRequest).get(request_id)
            if not request:
                raise NotFoundError("Request not found")

            if request.status != RequestStatus.OPEN:
                raise ValidationError("Request is no longer accepting offers")

            if request.expires_at < datetime.utcnow():
                raise ValidationError("Request has expired")

            # Check for existing offer from this seller
            existing_offer = (
                session.query(SellerOffer)
                .filter_by(request_id=request_id, seller_id=seller_id)
                .first()
            )

            if existing_offer:
                if existing_offer.status == OfferStatus.PENDING:
                    raise ConflictError(
                        "You already have a pending offer for this request"
                    )
                elif existing_offer.status == OfferStatus.ACCEPTED:
                    raise ConflictError("Your offer has already been accepted")

            # Validate product if provided
            if data.get("product_id"):
                product = session.query(Product).get(data["product_id"])
                if not product or product.seller_id != seller_id:
                    raise ValidationError("Invalid product")

            # Create offer
            offer = SellerOffer(
                request_id=request_id,
                seller_id=seller_id,
                product_id=data.get("product_id"),
                price=data.get("price"),
                message=data.get("message"),
                status=OfferStatus.PENDING,
            )

            session.add(offer)
            session.flush()

            # Notify buyer
            NotificationService.create_notification(
                user_id=request.user_id,
                notification_type=NotificationType.REQUEST_OFFER,
                actor_id=seller.user_id,
                reference_type="request",
                reference_id=request_id,
                metadata_={
                    "offer_id": offer.id,
                    "price": offer.price,
                    "seller_name": seller.shop_name,
                },
            )

            return offer

    @staticmethod
    def accept_offer(offer_id: int, user_id: str) -> SellerOffer:
        """Accept seller offer with conflict resolution"""
        with session_scope() as session:
            offer = (
                session.query(SellerOffer)
                .options(joinedload(SellerOffer.request))
                .get(offer_id)
            )

            if not offer:
                raise NotFoundError("Offer not found")

            # Validate request ownership
            if offer.request.user_id != user_id:
                raise ForbiddenError("Only request owner can accept offers")

            # Validate offer status
            if offer.status != OfferStatus.PENDING:
                raise ValidationError("Offer is no longer pending")

            # Validate request status
            if offer.request.status != RequestStatus.OPEN:
                raise ValidationError("Request is no longer accepting offers")

            # Reject all other offers for this request
            other_offers = (
                session.query(SellerOffer)
                .filter(
                    and_(
                        SellerOffer.request_id == offer.request_id,
                        SellerOffer.id != offer_id,
                        SellerOffer.status == OfferStatus.PENDING,
                    )
                )
                .all()
            )

            for other_offer in other_offers:
                other_offer.status = OfferStatus.REJECTED
                # Notify other sellers
                NotificationService.create_notification(
                    user_id=other_offer.seller.user_id,
                    notification_type=NotificationType.OFFER_REJECTED,
                    reference_type="request",
                    reference_id=offer.request_id,
                    metadata_={"request_title": offer.request.title},
                )

            # Accept the selected offer
            offer.status = OfferStatus.ACCEPTED

            # Update request status
            offer.request.status = RequestStatus.FULFILLED

            # Notify accepted seller
            NotificationService.create_notification(
                user_id=offer.seller.user_id,
                notification_type=NotificationType.OFFER_ACCEPTED,
                reference_type="request",
                reference_id=offer.request_id,
                metadata_={"request_title": offer.request.title, "price": offer.price},
            )

            # Cache invalidation
            BuyerRequestService._invalidate_request_cache(offer.request_id)

            return offer

    @staticmethod
    def list_user_requests(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get paginated list of user's requests"""
        cache_key = BuyerRequestService.CACHE_KEYS["user_requests"].format(
            user_id=user_id
        )

        # Try cache for read-only operations
        if not args.get("page", 1) == 1:  # Only cache first page
            cached = redis_client.get(cache_key)
            if cached:
                return cached

        with session_scope() as session:
            base_query = (
                session.query(BuyerRequest)
                .filter(BuyerRequest.user_id == user_id)
                .options(
                    joinedload(BuyerRequest.category),
                    joinedload(BuyerRequest.images),
                    joinedload(BuyerRequest.offers),
                )
                .order_by(BuyerRequest.created_at.desc())
            )

            # Apply filters
            if args.get("status"):
                base_query = base_query.filter(BuyerRequest.status == args["status"])

            paginator = Paginator(
                base_query, page=args.get("page", 1), per_page=args.get("per_page", 20)
            )
            result = paginator.paginate(args)

            # Cache first page for 5 minutes
            if args.get("page", 1) == 1:
                redis_client.setex(cache_key, 300, result)

            return result

    @staticmethod
    def search_requests(
        args: Dict[str, Any], user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search requests with role-based filtering"""
        with session_scope() as session:
            base_query = session.query(BuyerRequest).filter(
                BuyerRequest.status == RequestStatus.OPEN
            )

            # Apply search filters
            if args.get("search"):
                search_term = f"%{args['search']}%"
                base_query = base_query.filter(
                    or_(
                        BuyerRequest.title.ilike(search_term),
                        BuyerRequest.description.ilike(search_term),
                    )
                )

            if args.get("category_id"):
                base_query = base_query.filter(
                    BuyerRequest.category_id == args["category_id"]
                )

            if args.get("min_budget"):
                base_query = base_query.filter(
                    BuyerRequest.budget >= args["min_budget"]
                )

            if args.get("max_budget"):
                base_query = base_query.filter(
                    BuyerRequest.budget <= args["max_budget"]
                )

            # Role-based filtering
            if user_id:
                user = session.query(User).get(user_id)
                if user and user.is_buyer:
                    # Buyers see all open requests except their own
                    base_query = base_query.filter(BuyerRequest.user_id != user_id)
                elif user and user.is_seller:
                    # Sellers see all open requests
                    pass

            # Order by relevance (views, upvotes, recency)
            base_query = base_query.order_by(
                BuyerRequest.views.desc(),
                BuyerRequest.upvotes.desc(),
                BuyerRequest.created_at.desc(),
            )

            paginator = Paginator(
                base_query, page=args.get("page", 1), per_page=args.get("per_page", 20)
            )
            # return paginator.paginate(args)
            return paginator.paginate(args)

    @staticmethod
    def upvote_request(request_id: str, user_id: str) -> Dict[str, Any]:
        """Upvote a request (buyers only)"""
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not user or not user.is_buyer:
                raise ForbiddenError("Only buyers can upvote requests")

            request = session.query(BuyerRequest).get(request_id)
            if not request:
                raise NotFoundError("Request not found")

            # Prevent self-upvoting
            if request.user_id == user_id:
                raise ValidationError("Cannot upvote your own request")

            # Increment upvotes
            request.upvotes += 1

            # Cache invalidation
            BuyerRequestService._invalidate_request_cache(request_id)

            return {"upvotes": request.upvotes}

    # Private helper methods
    @staticmethod
    def _invalidate_request_cache(request_id: str):
        """Invalidate request-related caches"""
        redis_client.delete(
            BuyerRequestService.CACHE_KEYS["request"].format(request_id=request_id)
        )

    @staticmethod
    def _invalidate_user_cache(user_id: str):
        """Invalidate user-related caches"""
        redis_client.delete(
            BuyerRequestService.CACHE_KEYS["user_requests"].format(user_id=user_id)
        )

    @staticmethod
    def _invalidate_category_cache(category_id: Optional[int]):
        """Invalidate category-related caches"""
        if category_id:
            redis_client.delete(
                BuyerRequestService.CACHE_KEYS["category_requests"].format(
                    category_id=category_id
                )
            )

    @staticmethod
    def _notify_relevant_sellers(request: BuyerRequest):
        """Notify sellers who might be interested in the request"""
        # TODO: Implement smart seller matching based on:
        # - Category preferences
        # - Past successful offers
        # - Geographic proximity
        # - Price range preferences

    @staticmethod
    def _handle_request_closure(request: BuyerRequest, session):
        """Handle request closure logic"""
        # Reject all pending offers
        pending_offers = (
            session.query(SellerOffer)
            .filter_by(request_id=request.id, status=OfferStatus.PENDING)
            .all()
        )

        for offer in pending_offers:
            offer.status = OfferStatus.REJECTED
            NotificationService.create_notification(
                user_id=offer.seller.user_id,
                notification_type=NotificationType.REQUEST_CLOSED,
                reference_type="request",
                reference_id=request.id,
                metadata_={"request_title": request.title},
            )

    @staticmethod
    def _handle_request_expiration(request: BuyerRequest, session):
        """Handle request expiration logic"""
        # Similar to closure but with different notification
        BuyerRequestService._handle_request_closure(request, session)

    @staticmethod
    def _notify_status_change(
        request: BuyerRequest, old_status: RequestStatus, new_status: RequestStatus
    ):
        """Notify relevant parties of status changes"""
        # Notify request owner
        NotificationService.create_notification(
            user_id=request.user_id,
            notification_type=NotificationType.REQUEST_STATUS_CHANGE,
            reference_type="request",
            reference_id=request.id,
            metadata_={
                "old_status": old_status.value,
                "new_status": new_status.value,
                "request_title": request.title,
            },
        )
