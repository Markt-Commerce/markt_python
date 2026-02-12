from marshmallow import Schema, fields, validate
from app.libs.schemas import PaginationSchema
from .models import DeliveryStatus

class DeliveryLoginRequestSchema(Schema):
    phone_number = fields.String(required=True, validate=validate.Regexp(r"^\+?\d{10,15}$"))
    otp = fields.String(required=True, validate=validate.Length(equal=6))

class DeliveryLoginResponseSchema(Schema):
    partner = fields.Nested("PartnerSchema")


class PartnerSchema(Schema):
    id = fields.String()
    name = fields.String()
    status = fields.String(validate=validate.OneOf([DeliveryStatus.ACTIVE, DeliveryStatus.INACTIVE, DeliveryStatus.SUSPENDED]))

class DeliveryOTPRequestSchema(Schema):
    phone_number = fields.String(required=True, validate=validate.Regexp(r"^\+?\d{10,15}$"))

class DeliveryOTPResponseSchema(Schema):
    status = fields.String()
    message = fields.String()

class DeliveryDataResponseSchema(Schema):
    id = fields.String()
    name = fields.String()
    status = fields.String(validate=validate.OneOf([DeliveryStatus.ACTIVE, DeliveryStatus.INACTIVE, DeliveryStatus.SUSPENDED]))
    vehicle_type = fields.String()
    rating = fields.Float()

class DeliveryStatusUpdateSchema(Schema):
    status = fields.String(validate=validate.OneOf([DeliveryStatus.ACTIVE, DeliveryStatus.INACTIVE, DeliveryStatus.SUSPENDED]))

class DeliveryLocationRequestSchema(Schema):
    lat = fields.Float(required=True)
    lng = fields.Float(required=True)
    accuracy = fields.Float(required=False)
    speed = fields.Float(required=False)

class DeliveryLocationResponseSchema(Schema):
    status = fields.String()
    message = fields.String()

class DeliveryAvailableOrdersResponseSchema(Schema):
    range_meters = fields.Integer()
    orders = fields.List(fields.Nested("AvailableOrderSchema"))

class AvailableOrderSchema(Schema):
    order_id = fields.String()
    pickup = fields.Nested("LocationSchema")
    dropoff = fields.Nested("LocationSchema")
    distance_meters = fields.Integer()
    estimated_earnings = fields.Float()

class LocationSchema(Schema):
    lat = fields.Float()
    lng = fields.Float()

class DeliveryOrderAcceptRequestSchema(Schema):
    order_id = fields.String(required=True)

class DeliveryOrderAcceptResponseSchema(Schema):
    assignmentId = fields.String()
    status = fields.String(validate=validate.OneOf(["ASSIGNED", "REJECTED"]))


class DeliveryActiveAssignmentsResponseSchema(Schema):
    assignments = fields.List(fields.Nested("ActiveAssignmentSchema"))

class ActiveAssignmentSchema(Schema):
    assignmentId = fields.String()
    orderId = fields.String()
    pickup = fields.Nested("LocationSchema")
    dropoff = fields.Nested("LocationSchema")
    status = fields.String(validate=validate.OneOf(["EN_ROUTE_TO_PICKUP", "PICKED_UP", "DELIVERED"]))
    assignedAt = fields.DateTime()

# Request and response schema for updating logistical status of an active assignment
class LogisticStatusUpdateSchema(Schema):
    status = fields.String(validate=validate.OneOf(["ARRIVED_PICKUP", "PICKED_UP", "EN_ROUTE_TO_DROPOFF", "DELIVERED_PENDING_QR"]))


class DeliveryOrderQRResponseSchema(Schema):
    orderId = fields.String()
    qrCode = fields.String()

class DeliveryOrderQRConfirmRequestSchema(Schema):
    orderId = fields.String()
    qrCode = fields.String()

class DeliveryOrderQRConfirmResponseSchema(Schema):
    status = fields.String()
    message = fields.String()