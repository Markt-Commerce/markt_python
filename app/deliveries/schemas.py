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
