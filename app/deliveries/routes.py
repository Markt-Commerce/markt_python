# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, login_user, current_user
from marshmallow import fields

# project imports
from app.libs.decorators import admin_required
from app.libs.schemas import PaginationQueryArgs

# app imports
from .schemas import (
    DeliveryLoginRequestSchema,
    DeliveryLoginResponseSchema,
    DeliveryOTPRequestSchema,
    DeliveryOTPResponseSchema,
    DeliveryDataResponseSchema,
    DeliveryRegisterRequestSchema,
    DeliveryRegisterResponseSchema,
    DeliveryStatusUpdateSchema,
    DeliveryLocationRequestSchema,
    DeliveryLocationResponseSchema,
    DeliveryAvailableOrdersQuerySchema,
    DeliveryAvailableOrdersResponseSchema,
    DeliveryOrderAcceptRequestSchema,
    DeliveryOrderAcceptResponseSchema,
    DeliveryActiveAssignmentsResponseSchema,
    LogisticStatusUpdateSchema,
    DeliveryOrderQRResponseSchema,
    DeliveryOrderQRConfirmRequestSchema,
    DeliveryOrderQRConfirmResponseSchema,
    DeliveryAvailableRunsQuerySchema,
    DeliveryAvailableRunsResponseSchema,
    DeliveryRunDetailResponseSchema,
    DeliveryRunAcceptResponseSchema,
    DeliveryRunFailRequestSchema,
    DeliveryRunStopActionResponseSchema,
    DeliveryRunPickupConfirmResponseSchema,
    DeliveryRunOrderPodQRResponseSchema,
    DeliveryRunOrderPodConfirmRequestSchema,
    DeliveryRunOrderPodConfirmResponseSchema,
    DeliveryFailureReportRequestSchema,
    DeliveryFailureSchema,
    DeliveryFailureResolveRequestSchema,
    DeliveryFailureCompleteRequestSchema,
)
from app.libs.auth_tokens import generate_auth_token
from .services import DeliveryService
from .run_assignment import DeliveryRunAssignmentService
from .pickup import DeliveryRunPickupService, DeliveryRunPodService
from .failure import DeliveryFailureService
from .models import DeliveryCostBearer, DeliveryFailureReason, DeliveryRecoveryAction

bp = Blueprint(
    "deliveries",
    __name__,
    description="Delivery operations",
    url_prefix="/deliveries",
)


@bp.route("/auth/login")
class DeliveryLogin(MethodView):
    @bp.arguments(DeliveryLoginRequestSchema, location="json")
    @bp.response(200, DeliveryLoginResponseSchema)
    def post(self, data):
        """Login delivery partner; return partner (same pattern as users/login so session cookie is set)"""
        delivery_user = DeliveryService.login_delivery_partner(
            data["phone_number"], data["otp"]
        )
        login_user(delivery_user)
        return {
            "partner": {
                "id": delivery_user.id,
                "name": delivery_user.name,
                "status": delivery_user.status.value,
            },
            "access_token": generate_auth_token(delivery_user.id),
        }  # return dict, let flask-smorest build response (same flow as users/login → session cookie set)


@bp.route("/auth/register")
class DeliveryRegister(MethodView):
    @bp.arguments(DeliveryRegisterRequestSchema, location="json")
    @bp.response(201, DeliveryRegisterResponseSchema)
    def post(self, data):
        """Register a new delivery partner"""
        return DeliveryService.register_delivery_partner(data)


@bp.route("/auth/otp")
class DeliveryOTP(MethodView):
    @bp.arguments(DeliveryOTPRequestSchema, location="json")
    @bp.response(200, DeliveryOTPResponseSchema)
    def post(self, data):
        """Send OTP to delivery partner"""
        return DeliveryService.send_otp(data["phone_number"])


@bp.route("/partners/me")
class DeliveryPartnerMe(MethodView):
    @login_required
    @bp.response(200, DeliveryDataResponseSchema)
    def get(self):
        """Get current delivery partner details"""
        return DeliveryService.get_current_delivery_partner(
            current_user.id
        )  # TODO: This will require session management to link delivery partner to user session.


@bp.route("/partners/me/status")
class DeliveryPartnerStatus(MethodView):
    @login_required
    @bp.response(200, DeliveryStatusUpdateSchema)
    def patch(self):
        """Update current delivery partner status"""
        return DeliveryService.update_delivery_partner_status(
            current_user.id
        )  # TODO: This will require session management to link delivery partner to user session.


@bp.route("/partners/me/location")
class DeliveryLocation(MethodView):
    @login_required
    @bp.arguments(DeliveryLocationRequestSchema, location="json")
    @bp.response(200, DeliveryLocationResponseSchema)
    def post(self, data):
        """Update delivery partner location"""
        return DeliveryService.update_delivery_partner_location(current_user.id, data)


@bp.route("/orders/available")
class DeliveryAvailableOrders(MethodView):
    @login_required
    @bp.arguments(DeliveryAvailableOrdersQuerySchema, location="query")
    @bp.response(200, DeliveryAvailableOrdersResponseSchema)
    def get(self, args):
        """Get available orders for the delivery partner (paginated)."""
        return DeliveryService.get_available_orders(
            current_user.id,
            search_radius=args.get("search_radius", 5000),
            page=args.get("page", 1),
            per_page=args.get("per_page", 20),
        )


@bp.route("/orders/<string:order_id>/accept")
class DeliveryAcceptOrder(MethodView):
    @login_required
    @bp.response(200, DeliveryOrderAcceptResponseSchema)
    def post(self, order_id):
        """Accept an available order"""
        return DeliveryService.accept_order(current_user.id, order_id)


@bp.route("/orders/<string:order_id>/reject")
class DeliveryRejectOrder(MethodView):
    @login_required
    @bp.response(200, DeliveryOrderAcceptResponseSchema)
    def post(self, order_id):
        """Reject an available order"""
        return DeliveryService.reject_order(current_user.id, order_id)


@bp.route("/assignments/active")
class DeliveryActiveAssignments(MethodView):
    @login_required
    @bp.response(200, DeliveryActiveAssignmentsResponseSchema)
    def get(self):
        """Get active assignments for the delivery partner"""
        return DeliveryService.get_active_assignments(current_user.id)


@bp.route("/assignments/<string:assignment_id>/status")
class DeliveryAssignmentStatus(MethodView):
    @login_required
    @bp.arguments(LogisticStatusUpdateSchema, location="json")
    @bp.response(200, LogisticStatusUpdateSchema)
    def patch(self, data, assignment_id):
        """Update status of an active assignment (e.g., mark as completed)"""
        return DeliveryService.update_assignment_status(
            current_user.id, assignment_id, data["status"]
        )


@bp.route("/orders/<string:order_id>/qr")
class DeliveryOrderQR(MethodView):
    @login_required
    @bp.response(200, DeliveryOrderQRResponseSchema)
    def get(self, order_id):
        """Get QR code for order escrow release"""
        return DeliveryService.get_order_qr_code(current_user.id, order_id)


@bp.route("/orders/<string:order_id>/qr/confirm")
class DeliveryOrderQRConfirm(MethodView):
    @login_required
    @bp.arguments(DeliveryOrderQRConfirmRequestSchema, location="json")
    @bp.response(200, DeliveryOrderQRConfirmResponseSchema)
    def post(self, data, order_id):
        """Confirm QR code for order escrow release"""
        return DeliveryService.confirm_order_qr_code(
            current_user.id, order_id, data["qr_code"]
        )


@bp.route("/runs/available")
class DeliveryAvailableRuns(MethodView):
    @login_required
    @bp.arguments(DeliveryAvailableRunsQuerySchema, location="query")
    @bp.response(200, DeliveryAvailableRunsResponseSchema)
    def get(self, args):
        """10.6: get available delivery runs for the rider (paginated)."""
        return DeliveryRunAssignmentService.get_available_runs(
            current_user.id,
            search_radius=args.get("search_radius", 5000),
            page=args.get("page", 1),
            per_page=args.get("per_page", 20),
        )


@bp.route("/runs/active")
class DeliveryActiveRun(MethodView):
    @login_required
    @bp.response(200, DeliveryRunDetailResponseSchema)
    def get(self):
        """10.6: the rider's own run currently in progress (RIDER_ACCEPTED
        through DELIVERY_IN_PROGRESS), if any -- mirrors GET
        /assignments/active for the existing single-order flow. Returns
        {"run_id": null} rather than 404 when there's none."""
        return DeliveryRunAssignmentService.get_active_run(current_user.id)


@bp.route("/runs/<string:run_id>")
class DeliveryRunDetail(MethodView):
    @login_required
    @bp.response(200, DeliveryRunDetailResponseSchema)
    def get(self, run_id):
        """10.6: full detail for a run the rider has accepted -- per-
        seller pickup stops and per-order POD status. Used to refresh
        state after the thin accept_run response, or to recover on app
        restart."""
        return DeliveryRunAssignmentService.get_run_detail(current_user.id, run_id)


@bp.route("/runs/<string:run_id>/accept")
class DeliveryRunAccept(MethodView):
    @login_required
    @bp.response(200, DeliveryRunAcceptResponseSchema)
    def post(self, run_id):
        """10.6: accept an available delivery run."""
        return DeliveryRunAssignmentService.accept_run(current_user.id, run_id)


@bp.route("/runs/<string:run_id>/reject")
class DeliveryRunReject(MethodView):
    @login_required
    @bp.response(200, DeliveryRunAcceptResponseSchema)
    def post(self, run_id):
        """10.6: decline an available delivery run."""
        return DeliveryRunAssignmentService.reject_run(current_user.id, run_id)


@bp.route("/runs/<string:run_id>/fail")
class DeliveryRunFail(MethodView):
    @login_required
    @bp.arguments(DeliveryRunFailRequestSchema, location="json")
    @bp.response(200, DeliveryRunAcceptResponseSchema)
    def post(self, data, run_id):
        """10.7: rider reports they can no longer continue an accepted
        run -- triggers reassignment where possible."""
        return DeliveryRunAssignmentService.fail_run(
            current_user.id, run_id, reason=data.get("reason")
        )


@bp.route("/runs/<string:run_id>/stops/<int:seller_id>/arrive")
class DeliveryRunStopArrive(MethodView):
    @login_required
    @bp.response(200, DeliveryRunStopActionResponseSchema)
    def post(self, run_id, seller_id):
        """10.6: rider marks arrival at a seller pickup stop."""
        return DeliveryRunPickupService.arrive_at_stop(
            current_user.id, run_id, seller_id
        )


@bp.route("/runs/<string:run_id>/stops/<int:seller_id>/pickup")
class DeliveryRunStopPickup(MethodView):
    @login_required
    @bp.response(200, DeliveryRunPickupConfirmResponseSchema)
    def post(self, run_id, seller_id):
        """10.6: rider confirms pickup at a seller stop. Once every stop
        in the run is picked up, issues a POD QR per order and advances
        the run to DELIVERY_IN_PROGRESS."""
        return DeliveryRunPickupService.confirm_pickup_at_stop(
            current_user.id, run_id, seller_id
        )


@bp.route("/runs/<string:run_id>/orders/<string:order_id>/pod-qr")
class DeliveryRunOrderPodQR(MethodView):
    @login_required
    @bp.response(200, DeliveryRunOrderPodQRResponseSchema)
    def get(self, run_id, order_id):
        """10.6: get the POD QR code for one order within an accepted run."""
        return DeliveryRunPodService.get_order_pod_qr(current_user.id, run_id, order_id)


@bp.route("/runs/<string:run_id>/orders/<string:order_id>/pod-confirm")
class DeliveryRunOrderPodConfirm(MethodView):
    @login_required
    @bp.arguments(DeliveryRunOrderPodConfirmRequestSchema, location="json")
    @bp.response(200, DeliveryRunOrderPodConfirmResponseSchema)
    def post(self, data, run_id, order_id):
        """10.6: confirm proof-of-delivery for one order within a run --
        marks its items DELIVERED (starting the settlement hold, Phase 0)
        and completes the run once every attached order has confirmed."""
        return DeliveryRunPodService.confirm_order_pod(
            current_user.id, run_id, order_id, data["qr_code"]
        )


@bp.route("/runs/<string:run_id>/orders/<string:order_id>/report-failure")
class DeliveryRunOrderReportFailure(MethodView):
    @login_required
    @bp.arguments(DeliveryFailureReportRequestSchema, location="json")
    @bp.response(200, DeliveryFailureSchema)
    def post(self, data, run_id, order_id):
        """10.7: rider reports a failed delivery attempt with a typed
        reason."""
        return DeliveryFailureService.report_failure(
            current_user.id,
            run_id,
            order_id,
            DeliveryFailureReason(data["reason"]),
            notes=data.get("notes"),
        )


@bp.route("/failures/<string:failure_id>/resolve")
class DeliveryFailureResolve(MethodView):
    @admin_required
    @bp.arguments(DeliveryFailureResolveRequestSchema, location="json")
    @bp.response(200, DeliveryFailureSchema)
    def post(self, data, failure_id):
        """10.7: record the chosen recovery action and who bears the
        cost -- a support/business decision, not made by the reporting
        rider (admin-only)."""
        return DeliveryFailureService.resolve_failure(
            failure_id,
            DeliveryRecoveryAction(data["recovery_action"]),
            DeliveryCostBearer(data["cost_bearer"]),
            notes=data.get("notes"),
        )


@bp.route("/failures/<string:failure_id>/complete")
class DeliveryFailureComplete(MethodView):
    @admin_required
    @bp.arguments(DeliveryFailureCompleteRequestSchema, location="json")
    @bp.response(200, DeliveryFailureSchema)
    def post(self, data, failure_id):
        """10.7: mark the already-decided recovery action as actually
        carried out (admin-only)."""
        return DeliveryFailureService.complete_recovery(
            failure_id, notes=data.get("notes")
        )
