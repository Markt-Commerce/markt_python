# package imports
from flask import request
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user

# project imports
from app.libs.decorators import buyer_required, seller_required
from app.libs.errors import APIError

# app imports
from .services import FulfilmentService
from .schemas import FulfilmentAllocationSchema

bp = Blueprint(
    "fulfilment",
    __name__,
    description="Seller fulfilment operations",
    url_prefix="/fulfilment",
)


def _dump(allocation):
    return {
        "id": allocation.id,
        "order_item_id": allocation.order_item_id,
        "seller_id": allocation.seller_id,
        "quantity": allocation.quantity,
        "status": allocation.status.value,
        "seller_response_deadline": allocation.seller_response_deadline,
        "created_at": allocation.created_at,
        "updated_at": allocation.updated_at,
    }


@bp.route("/allocations")
class AllocationList(MethodView):
    @login_required
    @seller_required
    @bp.response(200)
    def get(self):
        """Seller-facing list of their own pending/in-progress fulfilment
        allocations (12.1-12.2) -- previously nothing let a seller see
        these at all outside the notification announcing one, which had
        nowhere to deep-link to. Defaults to active statuses (awaiting
        seller response through preparing); pass ?status=timeout etc. for
        a specific historical status instead."""
        from .services import FulfilmentService

        status = request.args.get("status")
        try:
            allocations = FulfilmentService.list_seller_allocations(
                current_user.seller_account.id, status=status
            )
        except APIError as e:
            abort(e.status_code, message=e.message)

        return [
            {
                "id": a.id,
                "order_item_id": a.order_item_id,
                "order_id": a.order_item.order_id if a.order_item else None,
                "seller_id": a.seller_id,
                "quantity": a.quantity,
                "product_name": a.product.name if a.product else None,
                "status": a.status.value,
                "seller_response_deadline": (
                    a.seller_response_deadline.isoformat()
                    if a.seller_response_deadline
                    else None
                ),
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in allocations
        ]


@bp.route("/allocations/<int:allocation_id>/accept")
class AllocationAccept(MethodView):
    @login_required
    @seller_required
    @bp.response(200, FulfilmentAllocationSchema)
    def post(self, allocation_id):
        """Seller accepts a fulfilment allocation (12.2)."""
        try:
            allocation = FulfilmentService.accept(
                allocation_id, current_user.seller_account.id
            )
            return _dump(allocation)
        except (APIError, ValueError) as e:
            message = getattr(e, "message", str(e))
            status_code = getattr(e, "status_code", 400)
            abort(status_code, message=message)


@bp.route("/allocations/<int:allocation_id>/decline")
class AllocationDecline(MethodView):
    @login_required
    @seller_required
    @bp.response(200, FulfilmentAllocationSchema)
    def post(self, allocation_id):
        """Seller declines a fulfilment allocation (12.2)."""
        try:
            allocation = FulfilmentService.decline(
                allocation_id, current_user.seller_account.id
            )
            return _dump(allocation)
        except (APIError, ValueError) as e:
            message = getattr(e, "message", str(e))
            status_code = getattr(e, "status_code", 400)
            abort(status_code, message=message)


@bp.route("/allocations/<int:allocation_id>/cancel")
class AllocationCancelAfterAccept(MethodView):
    @login_required
    @seller_required
    @bp.response(200, FulfilmentAllocationSchema)
    def post(self, allocation_id):
        """Seller backs out of an accepted/preparing allocation (13.4
        anti-gaming "accept-then-cancel") -- worse than decline() and
        scored accordingly by Seller Reliability's cancellation penalty."""
        try:
            allocation = FulfilmentService.cancel_after_accept(
                allocation_id, current_user.seller_account.id
            )
            return _dump(allocation)
        except (APIError, ValueError) as e:
            message = getattr(e, "message", str(e))
            status_code = getattr(e, "status_code", 400)
            abort(status_code, message=message)


@bp.route("/allocations/<int:allocation_id>/approve-substitution")
class AllocationApproveSubstitution(MethodView):
    @login_required
    @buyer_required
    @bp.response(200, FulfilmentAllocationSchema)
    def post(self, allocation_id):
        """Buyer approves a material substitution pending under their ASK
        preference (6.1)."""
        try:
            allocation = FulfilmentService.buyer_approve_reroute(
                allocation_id, current_user.buyer_account.id
            )
            return _dump(allocation)
        except (APIError, ValueError) as e:
            message = getattr(e, "message", str(e))
            status_code = getattr(e, "status_code", 400)
            abort(status_code, message=message)


@bp.route("/allocations/<int:allocation_id>/reject-substitution")
class AllocationRejectSubstitution(MethodView):
    @login_required
    @buyer_required
    @bp.response(200, FulfilmentAllocationSchema)
    def post(self, allocation_id):
        """Buyer rejects a material substitution pending under their ASK
        preference (6.1) -- the reroute loop tries the next candidate."""
        try:
            allocation = FulfilmentService.buyer_reject_reroute(
                allocation_id, current_user.buyer_account.id
            )
            return _dump(allocation)
        except (APIError, ValueError) as e:
            message = getattr(e, "message", str(e))
            status_code = getattr(e, "status_code", 400)
            abort(status_code, message=message)


@bp.route("/allocations/<int:allocation_id>/start-preparing")
class AllocationStartPreparing(MethodView):
    @login_required
    @seller_required
    @bp.response(200, FulfilmentAllocationSchema)
    def post(self, allocation_id):
        """Seller starts preparing an accepted allocation (12.2)."""
        try:
            allocation = FulfilmentService.start_preparing(
                allocation_id, current_user.seller_account.id
            )
            return _dump(allocation)
        except (APIError, ValueError) as e:
            message = getattr(e, "message", str(e))
            status_code = getattr(e, "status_code", 400)
            abort(status_code, message=message)
