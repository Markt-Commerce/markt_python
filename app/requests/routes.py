# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user

# project imports
from app.libs.decorators import buyer_required, seller_required
from app.libs.schemas import PaginationQueryArgs
from app.libs.errors import APIError

# app imports
from .services import BuyerRequestService
from .models import RequestStatus
from .schemas import (
    BuyerRequestSchema,
    BuyerRequestCreateSchema,
    BuyerRequestUpdateSchema,
    BuyerRequestSearchSchema,
    SellerOfferSchema,
    SellerOfferCreateSchema,
    RequestStatusUpdateSchema,
    BuyerRequestSearchResultSchema,
)


bp = Blueprint(
    "requests", __name__, description="Buyer request operations", url_prefix="/requests"
)


@bp.route("/")
class RequestList(MethodView):
    @bp.arguments(BuyerRequestSearchSchema, location="query")
    @bp.response(200, BuyerRequestSearchResultSchema)
    def get(self, args):
        """Search and list buyer requests with role-based filtering"""
        try:
            user_id = current_user.id if current_user.is_authenticated else None
            return BuyerRequestService.search_requests(args, user_id)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @buyer_required
    @bp.arguments(BuyerRequestCreateSchema)
    @bp.response(201, BuyerRequestSchema)
    def post(self, request_data):
        """Create new buyer request (buyers only)"""
        try:
            return BuyerRequestService.create_request(current_user.id, request_data)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/my-requests")
class MyRequests(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, BuyerRequestSearchResultSchema)
    def get(self, args):
        """Get current user's requests (buyers only)"""
        try:
            return BuyerRequestService.list_user_requests(current_user.id, args)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/<request_id>")
class RequestDetail(MethodView):
    @bp.response(200, BuyerRequestSchema)
    def get(self, request_id):
        """Get request details with role-based access control"""
        try:
            user_id = current_user.id if current_user.is_authenticated else None
            return BuyerRequestService.get_request(request_id, user_id)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @buyer_required
    @bp.arguments(BuyerRequestUpdateSchema)
    @bp.response(200, BuyerRequestSchema)
    def put(self, request_data, request_id):
        """Update request (owner only)"""
        try:
            return BuyerRequestService.update_request(
                request_id, current_user.id, request_data
            )
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @buyer_required
    @bp.response(204)
    def delete(self, request_id):
        """Delete request (owner only)"""
        try:
            BuyerRequestService.delete_request(request_id, current_user.id)
            return None
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/<request_id>/status")
class RequestStatusUpdate(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(RequestStatusUpdateSchema)
    @bp.response(200, BuyerRequestSchema)
    def put(self, status_data, request_id):
        """Update request status (owner only)"""
        try:
            new_status = RequestStatus(status_data["status"])
            return BuyerRequestService.update_request_status(
                request_id, current_user.id, new_status
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/<request_id>/upvote")
class RequestUpvote(MethodView):
    @login_required
    @buyer_required
    @bp.response(200)
    def post(self, request_id):
        """Upvote a request (buyers only)"""
        try:
            result = BuyerRequestService.upvote_request(request_id, current_user.id)
            return result
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/<request_id>/offers")
class RequestOffers(MethodView):
    @login_required
    @bp.response(200, SellerOfferSchema(many=True))
    def get(self, request_id):
        """Get offers for a request (request owner and offer creators only)"""
        try:
            return BuyerRequestService.list_request_offers(request_id, current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @seller_required
    @bp.arguments(SellerOfferCreateSchema)
    @bp.response(201, SellerOfferSchema)
    def post(self, offer_data, request_id):
        """Create offer for request (sellers only)"""
        try:
            return BuyerRequestService.create_offer(
                current_user.seller_account.id, request_id, offer_data
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/offers/<offer_id>/accept")
class OfferAccept(MethodView):
    @login_required
    @buyer_required
    @bp.response(200, SellerOfferSchema)
    def post(self, offer_id):
        """Accept an offer (request owner only)"""
        try:
            return BuyerRequestService.accept_offer(offer_id, current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/offers/<offer_id>/reject")
class OfferReject(MethodView):
    @login_required
    @buyer_required
    @bp.response(200, SellerOfferSchema)
    def post(self, offer_id):
        """Reject an offer (request owner only)"""
        try:
            return BuyerRequestService.reject_offer(offer_id, current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/offers/<offer_id>/withdraw")
class OfferWithdraw(MethodView):
    @login_required
    @seller_required
    @bp.response(200, SellerOfferSchema)
    def post(self, offer_id):
        """Withdraw an offer (offer creator only)"""
        try:
            return BuyerRequestService.withdraw_offer(
                offer_id, current_user.seller_account.id
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


# Note: Request image management is now handled via the media module
# Use /api/v1/media/requests/{request_id}/images for image operations
