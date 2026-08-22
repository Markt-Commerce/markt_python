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
    amount = fields.Float(
        validate=validate.Range(min=0),
        allow_none=True,
        metadata={
            "description": (
                "Optional. When provided, must match order.total exactly. "
                "Server always charges order.total."
            )
        },
    )
    currency = fields.Str(validate=validate.Length(equal=3), missing="NGN")
    method = fields.Str(missing="card")  # PaymentMethod.CARD.value
    metadata = fields.Dict(missing={})
    idempotency_key = fields.Str(
        allow_none=True
    )  # Optional idempotency key for retry safety


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

    # For saved-card charges (existing behaviour)
    authorization_code = fields.Str()
    card_token = fields.Str()

    # For bank transfer / direct‑debit style payments via Paystack Charge API.
    # We keep this generic so the frontend can pass through the exact structure
    # expected by Paystack, e.g.:
    # {
    #   "bank": {
    #       "code": "057",
    #       "account_number": "0000000000"
    #   }
    # }
    bank = fields.Dict(required=False)

    metadata = fields.Dict(missing={})


class CheckoutPaymentInitializeSchema(Schema):
    """Payment-first checkout: reserves stock and starts payment before any
    Order exists (additive alternative to CheckoutSchema/checkout_cart)."""

    shipping_address = fields.Dict(required=True)
    use_saved_address = fields.Bool(missing=False)
    platform = fields.Str(missing="web")
    reliability_fee_opted_in = fields.Bool(
        missing=False,
        metadata={
            "description": (
                "Opt-in only; only ever actually charged if a reroute "
                "fires (§11.2). Not captured today."
            )
        },
    )
    idempotency_key = fields.Str(allow_none=True)


class CheckoutPaymentResponseSchema(Schema):
    """Response for CheckoutPaymentInitializeSchema -- no order_id yet,
    since the order is only created once payment succeeds. Includes the
    full itemised breakdown (§11.5) so the client can render it before the
    buyer is sent to Paystack."""

    payment_id = fields.Str(required=True)
    authorization_url = fields.Str(allow_none=True)
    reference = fields.Str(allow_none=True)
    access_code = fields.Str(allow_none=True)
    amount = fields.Float(required=True)
    subtotal = fields.Float(required=True)
    shipping_fee = fields.Float(required=True)
    service_fee = fields.Float(required=True)
    reliability_fee_opted_in = fields.Bool(required=True)
    reliability_fee_estimate = fields.Float(required=True)
    capture_ceiling = fields.Float(
        required=True,
        metadata={
            "description": (
                "Max the buyer could be charged today, informational only "
                "(§11.4) -- not a PSP authorization hold."
            )
        },
    )


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
