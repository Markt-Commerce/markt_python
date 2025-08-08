# python imports
import logging
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List
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
from .models import BuyerRequest, SellerOffer, RequestStatus
from app.users.models import User, Seller
from app.products.models import Product
from app.notifications.services import NotificationService
from app.notifications.models import NotificationType
from app.media.services import media_service
from app.media.models import Media, RequestImage
from app.categories.models import Category, RequestCategory

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
    def _normalize_datetime(dt):
        """Convert datetime to UTC naive for consistent comparison"""
        if dt is None:
            return None
        if dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt

    @staticmethod
    def _serialize_request(request: BuyerRequest) -> Optional[str]:
        """Serialize request object for Redis caching"""
        try:
            # Convert to dict with serializable data
            request_data = {
                "id": request.id,
                "user_id": request.user_id,
                "title": request.title,
                "description": request.description,
                "category_id": request.category_id,
                "budget": float(request.budget) if request.budget else None,
                "request_metadata": request.request_metadata or {},
                "status": request.status.value if request.status else None,
                "views": request.views,
                "upvotes": request.upvotes,
                "created_at": request.created_at.isoformat()
                if request.created_at
                else None,
                "updated_at": request.updated_at.isoformat()
                if request.updated_at
                else None,
                "expires_at": request.expires_at.isoformat()
                if request.expires_at
                else None,
                "images": [
                    {
                        "id": img.id,
                        "image_url": img.image_url,
                        "is_primary": img.is_primary,
                    }
                    for img in getattr(request, "images", [])
                ],
                "offers_count": len(getattr(request, "offers", [])),
            }
            return json.dumps(request_data)
        except Exception as e:
            logger.error(f"Error serializing request: {e}")
            return None

    @staticmethod
    def _serialize_paginated_result(result: Dict[str, Any]) -> Optional[str]:
        """Serialize paginated result for Redis caching"""
        try:
            # Extract only the serializable parts
            serializable_result = {
                "items": [
                    {
                        "id": item.id,
                        "user_id": item.user_id,
                        "title": item.title,
                        "description": item.description,
                        "category_id": item.category_id,
                        "budget": float(item.budget) if item.budget else None,
                        "status": item.status.value if item.status else None,
                        "views": item.views,
                        "upvotes": item.upvotes,
                        "created_at": item.created_at.isoformat()
                        if item.created_at
                        else None,
                        "expires_at": item.expires_at.isoformat()
                        if item.expires_at
                        else None,
                        "images_count": len(item.images or []),
                        "offers_count": len(item.offers or []),
                    }
                    for item in result.get("items", [])
                ],
                "pagination": result.get("pagination", {}),
                "total": result.get("total", 0),
                "page": result.get("page", 1),
                "per_page": result.get("per_page", 20),
                "pages": result.get("pages", 1),
            }
            return json.dumps(serializable_result)
        except Exception as e:
            logger.error(f"Error serializing paginated result: {e}")
            return None

    @staticmethod
    def _deserialize_request(request_data: str) -> Optional[Dict[str, Any]]:
        """Deserialize request data from Redis cache"""
        try:
            return json.loads(request_data)
        except Exception as e:
            logger.error(f"Error deserializing request: {e}")
            return None

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
            else:
                # Normalize the datetime to UTC naive
                expires_at = BuyerRequestService._normalize_datetime(expires_at)

            # Create request
            request = BuyerRequest(
                user_id=user_id,
                title=data["title"],
                description=data["description"],
                budget=data.get("budget"),
                request_metadata=data.get("metadata", {}),
                expires_at=expires_at,
                status=RequestStatus.OPEN,
            )

            session.add(request)
            session.flush()

            # Handle category relationships
            if "category_ids" in data and data["category_ids"]:
                for idx, category_id in enumerate(data["category_ids"]):
                    # Verify category exists
                    category = session.query(Category).get(category_id)
                    if not category:
                        raise ValidationError(f"Category {category_id} not found")

                    # Create request category relationship
                    request_category = RequestCategory(
                        request_id=request.id,
                        category_id=category_id,
                        is_primary=(idx == 0),  # First category is primary
                    )
                    session.add(request_category)

            # Handle media linking if provided
            if "media_ids" in data and data["media_ids"]:
                for idx, media_id in enumerate(data["media_ids"]):
                    # Verify media exists and belongs to user
                    media = session.query(Media).get(media_id)
                    if not media:
                        raise ValidationError(f"Media {media_id} not found")

                    if media.user_id != user_id:
                        raise ValidationError(
                            f"Media {media_id} does not belong to you"
                        )

                    # Create request image relationship
                    request_image = RequestImage(
                        request_id=request.id,
                        media_id=media_id,
                        is_primary=(idx == 0),  # First image is primary
                        sort_order=idx,
                    )
                    session.add(request_image)

            # Cache invalidation
            BuyerRequestService._invalidate_user_cache(user_id)
            if "category_ids" in data and data["category_ids"]:
                for category_id in data["category_ids"]:
                    BuyerRequestService._invalidate_category_cache(category_id)

            # Create notification for relevant sellers
            BuyerRequestService._notify_relevant_sellers(request)

            return request

    @staticmethod
    def get_request(request_id: str, user_id: Optional[str] = None) -> BuyerRequest:
        """Get request details with role-based access control"""
        # TODO: Implement proper Redis caching with serialization
        # For now, disable caching to fix Redis DataError

        with session_scope() as session:
            request = (
                session.query(BuyerRequest)
                .options(
                    joinedload(BuyerRequest.user),
                    joinedload(BuyerRequest.categories).joinedload(
                        RequestCategory.category
                    ),
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
                        current_time = datetime.utcnow()
                        request_expires = BuyerRequestService._normalize_datetime(
                            request.expires_at
                        )
                        if (
                            request.status != RequestStatus.OPEN
                            or request_expires < current_time
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

            # Check if request has expired using normalized datetime
            current_time = datetime.utcnow()
            request_expires = BuyerRequestService._normalize_datetime(
                request.expires_at
            )
            if request_expires < current_time:
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
                status="pending",
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
        # TODO: Implement proper Redis caching with serialization
        # For now, disable caching to fix Redis DataError

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

            # TODO: Implement proper Redis caching with serialization
            # For now, disable caching to fix Redis DataError

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

            # Queue async real-time event (non-blocking)
            try:
                from app.realtime.event_manager import EventManager

                EventManager.emit_to_request(
                    request_id,
                    "request_upvoted",
                    {
                        "request_id": request_id,
                        "user_id": user_id,
                        "username": user.username if user else "Unknown",
                        "upvote_count": request.upvotes,
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to queue request_upvoted event: {e}")

            return {"upvotes": request.upvotes}

    @staticmethod
    def update_request(
        request_id: str, user_id: str, data: Dict[str, Any]
    ) -> BuyerRequest:
        """Update request details (owner only)"""
        with session_scope() as session:
            request = session.query(BuyerRequest).get(request_id)
            if not request:
                raise NotFoundError("Request not found")

            # Validate ownership
            if request.user_id != user_id:
                raise ForbiddenError("Only request owner can update request")

            # Validate request is still editable
            if request.status != RequestStatus.OPEN:
                raise ValidationError("Cannot update closed or fulfilled request")

            # Update fields
            if data.get("title"):
                request.title = data["title"]
            if data.get("description"):
                request.description = data["description"]
            if data.get("category_id"):
                request.category_id = data["category_id"]
            if data.get("budget"):
                request.budget = data["budget"]
            if data.get("metadata"):
                request.request_metadata.update(data["metadata"])
            if data.get("expires_at"):
                # Normalize the datetime to UTC naive
                expires_at = BuyerRequestService._normalize_datetime(data["expires_at"])
                request.expires_at = expires_at

            # Handle images if provided
            if data.get("images"):
                # Remove existing images
                session.query(RequestImage).filter_by(request_id=request_id).delete()

                # Add new images
                for i, image_data in enumerate(data["images"]):
                    image = RequestImage(
                        request_id=request.id,
                        image_url=image_data["url"],
                        is_primary=image_data.get(
                            "is_primary", i == 0
                        ),  # Use provided is_primary or default to first image
                    )
                    session.add(image)

            session.flush()

            # Cache invalidation
            BuyerRequestService._invalidate_request_cache(request_id)
            BuyerRequestService._invalidate_user_cache(user_id)
            BuyerRequestService._invalidate_category_cache(request.category_id)

            return request

    @staticmethod
    def delete_request(request_id: str, user_id: str) -> bool:
        """Delete request (owner only)"""
        with session_scope() as session:
            request = session.query(BuyerRequest).get(request_id)
            if not request:
                raise NotFoundError("Request not found")

            # Validate ownership
            if request.user_id != user_id:
                raise ForbiddenError("Only request owner can delete request")

            # Check if request has accepted offers
            accepted_offers = (
                session.query(SellerOffer)
                .filter_by(request_id=request_id, status=OfferStatus.ACCEPTED)
                .count()
            )
            if accepted_offers > 0:
                raise ValidationError("Cannot delete request with accepted offers")

            # Delete related data
            session.query(RequestImage).filter_by(request_id=request_id).delete()
            session.query(SellerOffer).filter_by(request_id=request_id).delete()
            session.delete(request)

            # Cache invalidation
            BuyerRequestService._invalidate_request_cache(request_id)
            BuyerRequestService._invalidate_user_cache(user_id)
            BuyerRequestService._invalidate_category_cache(request.category_id)

            return True

    @staticmethod
    def reject_offer(offer_id: int, user_id: str) -> SellerOffer:
        """Reject an offer (request owner only)"""
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
                raise ForbiddenError("Only request owner can reject offers")

            # Validate offer status
            if offer.status != OfferStatus.PENDING:
                raise ValidationError("Can only reject pending offers")

            # Update offer status
            offer.status = OfferStatus.REJECTED
            offer.updated_at = datetime.utcnow()

            # Notify seller
            NotificationService.create_notification(
                user_id=offer.seller.user_id,
                notification_type=NotificationType.OFFER_REJECTED,
                reference_type="offer",
                reference_id=offer.id,
                metadata_={
                    "request_title": offer.request.title,
                    "price": offer.price,
                },
            )

            # Cache invalidation
            BuyerRequestService._invalidate_request_cache(offer.request_id)

            return offer

    @staticmethod
    def withdraw_offer(offer_id: int, seller_id: int) -> SellerOffer:
        """Withdraw an offer (offer creator only)"""
        with session_scope() as session:
            offer = (
                session.query(SellerOffer)
                .options(joinedload(SellerOffer.request))
                .get(offer_id)
            )
            if not offer:
                raise NotFoundError("Offer not found")

            # Validate offer ownership
            if offer.seller_id != seller_id:
                raise ForbiddenError("Only offer creator can withdraw offer")

            # Validate offer status
            if offer.status != OfferStatus.PENDING:
                raise ValidationError("Can only withdraw pending offers")

            # Update offer status
            offer.status = OfferStatus.WITHDRAWN
            offer.updated_at = datetime.utcnow()

            # Notify request owner
            NotificationService.create_notification(
                user_id=offer.request.user_id,
                notification_type=NotificationType.OFFER_WITHDRAWN,
                reference_type="offer",
                reference_id=offer.id,
                metadata_={
                    "request_title": offer.request.title,
                    "seller_name": offer.seller.shop_name,
                },
            )

            # Cache invalidation
            BuyerRequestService._invalidate_request_cache(offer.request_id)

            return offer

    @staticmethod
    def list_request_offers(request_id: str, user_id: str) -> List[SellerOffer]:
        """Get offers for a request with access control"""
        with session_scope() as session:
            request = session.query(BuyerRequest).get(request_id)
            if not request:
                raise NotFoundError("Request not found")

            # Get user for access control
            user = session.query(User).get(user_id)
            if not user:
                raise ForbiddenError("Authentication required")

            # Access control: request owner sees all offers, offer creators see their own
            if request.user_id == user_id:
                # Request owner can see all offers
                offers = (
                    session.query(SellerOffer)
                    .filter_by(request_id=request_id)
                    .options(joinedload(SellerOffer.seller))
                    .order_by(SellerOffer.created_at.desc())
                    .all()
                )
            elif user.is_seller:
                # Sellers can only see their own offers
                offers = (
                    session.query(SellerOffer)
                    .filter_by(request_id=request_id, seller_id=user.seller_account.id)
                    .options(joinedload(SellerOffer.seller))
                    .order_by(SellerOffer.created_at.desc())
                    .all()
                )
            else:
                raise ForbiddenError("Access denied")

            return offers

    @staticmethod
    def handle_request_expiration():
        """Background task to handle expired requests"""
        with session_scope() as session:
            current_time = datetime.utcnow()
            expired_requests = (
                session.query(BuyerRequest)
                .filter(
                    and_(
                        BuyerRequest.status == RequestStatus.OPEN,
                        BuyerRequest.expires_at < current_time,
                    )
                )
                .all()
            )

            for request in expired_requests:
                BuyerRequestService._handle_request_expiration(request, session)

    @staticmethod
    def smart_seller_matching(request_id: str) -> List[Seller]:
        """Find relevant sellers for a request based on criteria"""
        with session_scope() as session:
            request = session.query(BuyerRequest).get(request_id)
            if not request:
                raise NotFoundError("Request not found")

            # Get sellers in the same category
            base_query = session.query(Seller).filter(Seller.is_verified == True)

            if request.category_id:
                base_query = base_query.filter(
                    Seller.category_id == request.category_id
                )

            # Filter by budget range if specified
            if request.budget:
                # Find sellers with products in similar price range
                base_query = base_query.join(Product).filter(
                    Product.price.between(request.budget * 0.5, request.budget * 1.5)
                )

            # Order by relevance (rating, completion rate, etc.)
            sellers = (
                base_query.order_by(Seller.rating.desc(), Seller.completion_rate.desc())
                .limit(20)
                .all()
            )

            return sellers

    @staticmethod
    def add_request_image(
        request_id: str,
        file_stream,
        filename: str,
        user_id: str,
        is_primary: bool = False,
    ):
        """Add image to buyer request"""
        try:
            from io import BytesIO
            from app.media.models import RequestImage

            # Ensure file_stream is BytesIO
            if not isinstance(file_stream, BytesIO):
                file_stream = BytesIO(file_stream.read())

            with session_scope() as session:
                # Verify request exists and user owns it
                request = session.query(BuyerRequest).get(request_id)
                if not request:
                    raise NotFoundError("Buyer request not found")

                if request.user_id != user_id:
                    raise ForbiddenError("You can only add images to your own requests")

                # 1. Upload media using updated media service (returns only media object)
                media = media_service.upload_image(
                    file_stream=file_stream,
                    filename=filename,
                    user_id=user_id,
                    alt_text=f"Request image for {request_id}",
                    caption="Buyer request image",
                )

                # 2. Create request image relationship
                request_image = RequestImage(
                    request_id=request_id, media_id=media.id, is_primary=is_primary
                )

                session.add(request_image)
                session.flush()

                return request_image

        except Exception as e:
            logger.error(f"Failed to add request image: {e}")
            raise ValidationError(f"Failed to add request image: {str(e)}")

    @staticmethod
    def get_request_images(request_id: str):
        """Get all images for a buyer request"""
        with session_scope() as session:
            from app.media.models import RequestImage

            return session.query(RequestImage).filter_by(request_id=request_id).all()

    @staticmethod
    def delete_request_image(image_id: int, user_id: str):
        """Delete a request image"""
        try:
            with session_scope() as session:
                from app.media.models import RequestImage

                request_image = session.query(RequestImage).get(image_id)
                if not request_image:
                    raise NotFoundError("Request image not found")

                # Verify user owns the request
                if request_image.request.user_id != user_id:
                    raise ForbiddenError(
                        "You can only delete images from your own requests"
                    )

                # Get the media object
                media = request_image.media
                if media:
                    # Delete from S3 using media service
                    success = media_service.delete_media(media)
                    if not success:
                        logger.warning(f"Failed to delete media {media.id} from S3")

                    # Delete media object from database
                    session.delete(media)

                # Delete request image relationship
                session.delete(request_image)
                session.flush()

                return {"success": True, "message": "Request image deleted"}

        except Exception as e:
            logger.error(f"Failed to delete request image: {e}")
            raise ValidationError(f"Failed to delete request image: {str(e)}")

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
