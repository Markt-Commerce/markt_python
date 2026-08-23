from marshmallow import Schema, fields, validate
from app.libs.schemas import PaginationSchema


class DeliveryLoginRequestSchema(Schema):
    phone_number = fields.String(
        required=True, validate=validate.Regexp(r"^\+?\d{10,15}$")
    )
    otp = fields.String(required=True, validate=validate.Length(equal=6))


class DeliveryLoginResponseSchema(Schema):
    partner = fields.Nested("PartnerSchema")


class DeliveryRegisterRequestSchema(Schema):
    phone_number = fields.String(
        required=True, validate=validate.Regexp(r"^\+?\d{10,15}$")
    )
    name = fields.String(required=True)
    vehicle_type = fields.String(
        validate=validate.OneOf(["BIKE", "CAR", "VAN", "TRUCK"])
    )
    email = fields.String(required=True, validate=validate.Email())


class DeliveryRegisterResponseSchema(Schema):
    id = fields.String()
    name = fields.String()
    vehicle_type = fields.String()
    status = fields.String()


class PartnerSchema(Schema):
    id = fields.String()
    name = fields.String()
    status = fields.String(validate=validate.OneOf(["ACTIVE", "INACTIVE", "SUSPENDED"]))


class DeliveryOTPRequestSchema(Schema):
    phone_number = fields.String(
        required=True, validate=validate.Regexp(r"^\+?\d{10,15}$")
    )


class DeliveryOTPResponseSchema(Schema):
    status = fields.String()
    message = fields.String()


class DeliveryDataResponseSchema(Schema):
    id = fields.String()
    name = fields.String()
    status = fields.String(validate=validate.OneOf(["ACTIVE", "INACTIVE", "SUSPENDED"]))
    vehicle_type = fields.String()
    rating = fields.Float()


class DeliveryStatusUpdateSchema(Schema):
    status = fields.String(validate=validate.OneOf(["ACTIVE", "INACTIVE", "SUSPENDED"]))


class DeliveryLocationRequestSchema(Schema):
    lat = fields.Float(required=True)
    lng = fields.Float(required=True)
    accuracy = fields.Float(required=False)
    speed = fields.Float(required=False)


class DeliveryLocationResponseSchema(Schema):
    status = fields.String()
    message = fields.String()


class DeliveryAvailableOrdersQuerySchema(Schema):
    page = fields.Int(validate=validate.Range(min=1), missing=1)
    per_page = fields.Int(validate=validate.Range(min=1, max=50), missing=20)
    search_radius = fields.Int(
        validate=validate.Range(min=100, max=50000), missing=5000
    )


class DeliveryAvailableOrdersResponseSchema(Schema):
    range_meters = fields.Integer()
    orders = fields.List(fields.Nested("AvailableOrderSchema"))
    page = fields.Integer()
    per_page = fields.Integer()
    total = fields.Integer()
    total_pages = fields.Integer()


class AvailableOrderSchema(Schema):
    order_id = fields.String()
    pickup = fields.List(fields.Nested("LocationSchema"))
    dropoff = fields.Nested("LocationSchema")
    distance_meters = fields.Float()
    estimated_earnings = fields.Float()


class LocationSchema(Schema):
    lat = fields.Float()
    lng = fields.Float()


class DeliveryOrderAcceptRequestSchema(Schema):
    order_id = fields.String(required=True)


class DeliveryOrderAcceptResponseSchema(Schema):
    assignment_id = fields.String()
    status = fields.String(validate=validate.OneOf(["ASSIGNED", "REJECTED"]))


class DeliveryActiveAssignmentsResponseSchema(Schema):
    assignments = fields.List(fields.Nested("ActiveAssignmentSchema"))


class ActiveAssignmentSchema(Schema):
    assignment_id = fields.String()
    order_id = fields.String()
    pickup = fields.List(fields.Nested("LocationSchema"))
    dropoff = fields.Nested("LocationSchema")
    status = fields.String(
        validate=validate.OneOf(["ASSIGNED", "ACCEPTED", "REJECTED"])
    )
    assignedAt = fields.DateTime()


# Request and response schema for updating logistical status of an active assignment
class LogisticStatusUpdateSchema(Schema):
    status = fields.String(
        validate=validate.OneOf(
            [
                "ARRIVED_PICKUP",
                "PICKED_UP",
                "EN_ROUTE_TO_DROPOFF",
                "DELIVERED_PENDING_QR",
                "COMPLETED",
            ]
        )
    )


class DeliveryOrderQRResponseSchema(Schema):
    order_id = fields.String()
    qr_code = fields.String()


class DeliveryOrderQRConfirmRequestSchema(Schema):
    order_id = fields.String()
    qr_code = fields.String()


class DeliveryOrderQRConfirmResponseSchema(Schema):
    status = fields.String()
    message = fields.String()


# --- DeliveryRun rider assignment (10.6-10.7, Phase 10) ---------------------


class DeliveryAvailableRunsQuerySchema(Schema):
    page = fields.Int(validate=validate.Range(min=1), missing=1)
    per_page = fields.Int(validate=validate.Range(min=1, max=50), missing=20)
    search_radius = fields.Int(
        validate=validate.Range(min=100, max=50000), missing=5000
    )


class AvailableRunSchema(Schema):
    run_id = fields.String()
    market = fields.String(allow_none=True)
    area = fields.String()
    order_count = fields.Integer()
    price_per_order = fields.Float(allow_none=True)
    distance_meters = fields.Float()


class DeliveryAvailableRunsResponseSchema(Schema):
    range_meters = fields.Integer()
    runs = fields.List(fields.Nested(AvailableRunSchema))
    page = fields.Integer()
    per_page = fields.Integer()
    total = fields.Integer()
    total_pages = fields.Integer()


class DeliveryRunAcceptResponseSchema(Schema):
    run_id = fields.String()
    status = fields.String()
    assignment_id = fields.Integer(allow_none=True)


class DeliveryRunFailRequestSchema(Schema):
    reason = fields.String(allow_none=True)


# --- DeliveryRun pickup-per-stop / POD (10.6, Phase 10) ---------------------


class DeliveryRunStopActionResponseSchema(Schema):
    delivery_run_id = fields.String()
    seller_id = fields.Integer()
    status = fields.String(validate=validate.OneOf(["pending", "arrived", "picked_up"]))


class DeliveryRunPickupConfirmResponseSchema(DeliveryRunStopActionResponseSchema):
    run_status = fields.String()
    pod_issued_for_orders = fields.List(fields.String())


class DeliveryRunOrderPodQRResponseSchema(Schema):
    order_id = fields.String()
    qr_code = fields.String()


class DeliveryRunOrderPodConfirmRequestSchema(Schema):
    qr_code = fields.String(required=True)


class DeliveryRunOrderPodConfirmResponseSchema(Schema):
    status = fields.String()
    message = fields.String()
    run_completed = fields.Boolean()


# --- Delivery failure & recovery (10.7, Phase 10) ---------------------------


class DeliveryFailureReportRequestSchema(Schema):
    reason = fields.String(
        required=True,
        validate=validate.OneOf(["buyer_unavailable", "bad_address", "buyer_refused"]),
    )
    notes = fields.String(allow_none=True)


class DeliveryFailureSchema(Schema):
    id = fields.String()
    delivery_run_id = fields.String(allow_none=True)
    order_id = fields.String()
    reason = fields.String()
    is_perishable = fields.Boolean()
    outcome = fields.String()
    recovery_action = fields.String(allow_none=True)
    cost_bearer = fields.String(allow_none=True)
    resolution_notes = fields.String(allow_none=True)
    reported_at = fields.DateTime(allow_none=True)
    resolved_at = fields.DateTime(allow_none=True)
    completed_at = fields.DateTime(allow_none=True)


class DeliveryFailureResolveRequestSchema(Schema):
    recovery_action = fields.String(
        required=True,
        validate=validate.OneOf(["redelivery", "return_to_seller", "dispose"]),
    )
    cost_bearer = fields.String(
        required=True, validate=validate.OneOf(["buyer", "seller", "markt"])
    )
    notes = fields.String(allow_none=True)


class DeliveryFailureCompleteRequestSchema(Schema):
    notes = fields.String(allow_none=True)
