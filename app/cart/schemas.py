from marshmallow import Schema, fields, validate


class CartItemSchema(Schema):
    product_id = fields.Str(required=True)
    variant_id = fields.Int(required=False)
    quantity = fields.Int(required=True, validate=validate.Range(min=1))
    price = fields.Float(dump_only=True)


class CartSchema(Schema):
    id = fields.Int(dump_only=True)
    items = fields.List(fields.Nested(CartItemSchema))
    subtotal = fields.Float(dump_only=True)
    expires_at = fields.DateTime(dump_only=True)


class AddToCartSchema(Schema):
    product_id = fields.Str(required=True)
    variant_id = fields.Int(required=False)
    quantity = fields.Int(validate=validate.Range(min=1), default=1)


class CheckoutSchema(Schema):
    shipping_address = fields.Dict(required=True)
    payment_method = fields.Str(required=True)
    coupon_code = fields.Str()
