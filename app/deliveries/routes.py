# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, current_user
from marshmallow import fields

# project imports
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
    DeliveryAvailableOrdersResponseSchema,
    DeliveryOrderAcceptRequestSchema,
    DeliveryOrderAcceptResponseSchema,
    DeliveryActiveAssignmentsResponseSchema,
    LogisticStatusUpdateSchema,
    DeliveryOrderQRResponseSchema,
    DeliveryOrderQRConfirmRequestSchema,
    DeliveryOrderQRConfirmResponseSchema,
)
from .services import DeliveryService

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
        """Login delivery partner and return partner details"""
        #TODO: Will need to implement session management and token generation for delivery partners.
        return DeliveryService.login_delivery_partner(data["phone_number"], data["otp"])

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
        return DeliveryService.get_current_delivery_partner(current_user.id) #TODO: This will require session management to link delivery partner to user session.

@bp.route("/partners/me/status")
class DeliveryPartnerStatus(MethodView):
    @login_required
    @bp.response(200, DeliveryStatusUpdateSchema)
    def patch(self):
        """Update current delivery partner status"""
        return DeliveryService.update_delivery_partner_status(current_user.id) #TODO: This will require session management to link delivery partner to user session.

@bp.route("/partners/me/location")
class DeliveryLocation(MethodView):
    @bp.arguments(DeliveryLocationRequestSchema, location="json")
    @bp.response(200, DeliveryLocationResponseSchema)
    def post(self, data):
        """Update delivery partner location"""
        return DeliveryService.update_delivery_partner_location(current_user.id, data["location"])
    

@bp.route("/orders/available")
class DeliveryAvailableOrders(MethodView):
    @login_required
    @bp.response(200, DeliveryAvailableOrdersResponseSchema)
    def get(self):
        """Get available orders for the delivery partner"""
        return DeliveryService.get_available_orders(current_user.id)

@bp.route("/orders/<string:order_id>/accept")
class DeliveryAcceptOrder(MethodView):
    @login_required
    @bp.arguments(DeliveryOrderAcceptRequestSchema, location="query")
    @bp.response(200, DeliveryOrderAcceptResponseSchema)
    def post(self, order_id, data):
        """Accept an available order"""
        return DeliveryService.accept_order(current_user.id, order_id)
    
@bp.route("/orders/<string:order_id>/reject")
class DeliveryRejectOrder(MethodView):
    @login_required
    @bp.arguments(DeliveryOrderAcceptRequestSchema, location="query")
    @bp.response(200, DeliveryOrderAcceptResponseSchema)
    def post(self, order_id, data):
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
    def patch(self, assignment_id, data):
        """Update status of an active assignment (e.g., mark as completed)"""
        return DeliveryService.update_assignment_status(current_user.id, assignment_id, data["status"])
    
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
    def post(self, order_id, data):
        """Confirm QR code for order escrow release"""
        return DeliveryService.confirm_order_qr_code(current_user.id, order_id, data["qrCode"])