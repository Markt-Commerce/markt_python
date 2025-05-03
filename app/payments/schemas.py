from marshmallow import Schema, fields, validate


class PaymentSchema(Schema):
    method = fields.Str(required=True)
    card_token = fields.Str(required=False)  # For card payments
    mobile_number = fields.Str(required=False)  # For mobile money
