# package imports
from marshmallow import Schema, fields, validate, post_load

# app imports
from .models import PaymentStatus, PaymentMethod


class PaymentSchema(Schema):
    """Payment response schema"""

    id = fields.Str(dump_only=True)
    order_id = fields.Str(required=True)
    amount = fields.Float(required=True, validate=validate.Range(min=0))
    currency = fields.Str(validate=validate.Length(equal=3))
    method = fields.Str(required=True)  # Will be PaymentMethod enum value
    status = fields.Str(dump_only=True)  # Will be PaymentStatus enum value
    transaction_id = fields.Str(dump_only=True)
    gateway_response = fields.Dict(dump_only=True)
    paid_at = fields.DateTime(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class PaymentCreateSchema(Schema):
    """Payment creation schema"""

    order_id = fields.Str(required=True)
    amount = fields.Float(required=True, validate=validate.Range(min=0))
    currency = fields.Str(validate=validate.Length(equal=3), missing="NGN")
    method = fields.Str(missing="card")  # PaymentMethod.CARD.value
    metadata = fields.Dict(missing={})


class PaymentVerifySchema(Schema):
    """Payment verification schema"""

    verified = fields.Bool(required=True)
    amount = fields.Float()
    gateway_response = fields.Dict()


class PaymentListSchema(Schema):
    """Payment list response schema"""

    payments = fields.Nested(PaymentSchema, many=True)
    total = fields.Int()
    page = fields.Int()
    per_page = fields.Int()
    pages = fields.Int()


class PaymentProcessSchema(Schema):
    """Payment processing schema"""

    authorization_code = fields.Str()
    card_token = fields.Str()
    metadata = fields.Dict(missing={})


class PaymentCallbackSchema(Schema):
    """Payment callback schema"""

    reference = fields.Str(required=True)
    status = fields.Str()
    amount = fields.Float()
    currency = fields.Str()
    metadata = fields.Dict()


class PaymentStatsSchema(Schema):
    """Payment statistics schema"""

    total_payments = fields.Int()
    successful_payments = fields.Int()
    failed_payments = fields.Int()
    total_revenue = fields.Float()
    currency = fields.Str(missing="NGN")
