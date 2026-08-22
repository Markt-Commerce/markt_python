# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user

# project imports
from app.libs.decorators import seller_required
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


@bp.route("/allocations/<int:allocation_id>/accept")
class AllocationAccept(MethodView):
    @login_required
    @seller_required
    @bp.response(200, FulfilmentAllocationSchema)
    def post(self, allocation_id):
        """Seller accepts a fulfilment allocation (§12.2)."""
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
        """Seller declines a fulfilment allocation (§12.2)."""
        try:
            allocation = FulfilmentService.decline(
                allocation_id, current_user.seller_account.id
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
        """Seller starts preparing an accepted allocation (§12.2)."""
        try:
            allocation = FulfilmentService.start_preparing(
                allocation_id, current_user.seller_account.id
            )
            return _dump(allocation)
        except (APIError, ValueError) as e:
            message = getattr(e, "message", str(e))
            status_code = getattr(e, "status_code", 400)
            abort(status_code, message=message)
