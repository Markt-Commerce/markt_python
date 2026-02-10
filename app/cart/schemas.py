from marshmallow import Schema, fields, validate

from app.products.schemas import ProductSchema


class CartItemSchema(Schema):
    """Schema for cart item"""

    id = fields.Int(dump_only=True)
    product_id = fields.Str(required=True)
    variant_id = fields.Int(allow_none=True)
    quantity = fields.Int(validate=validate.Range(min=1), required=True)
    product_price = fields.Float(dump_only=True)
    product = fields.Nested(ProductSchema, dump_only=True)


class CartSchema(Schema):
    """Schema for cart"""

    id = fields.Int(dump_only=True)
    buyer_id = fields.Int(dump_only=True)
    expires_at = fields.DateTime(dump_only=True)
    coupon_code = fields.Str(allow_none=True)
    items = fields.Nested(CartItemSchema, many=True, dump_only=True)
    total_items = fields.Method("get_total_items", dump_only=True)
    subtotal = fields.Method("get_subtotal", dump_only=True)

    def get_total_items(self, obj):
        return obj.total_items() if obj else 0

    def get_subtotal(self, obj):
        return obj.subtotal() if obj else 0


class AddToCartSchema(Schema):
    """Schema for adding item to cart"""

    product_id = fields.Str(required=True)
    quantity = fields.Int(validate=validate.Range(min=1), missing=1)
    variant_id = fields.Int(allow_none=True)


class UpdateCartItemSchema(Schema):
    """Schema for updating cart item"""

    quantity = fields.Int(validate=validate.Range(min=0), required=True)


class CheckoutSchema(Schema):
    """Schema for checkout"""

    shipping_address = fields.Dict(required=True)
    billing_address = fields.Dict(required=True)
    notes = fields.Str(allow_none=True)
    idempotency_key = fields.Str(
        allow_none=True
    )  # Optional idempotency key for retry safety


class CartSummarySchema(Schema):
    """Schema for cart summary"""

    item_count = fields.Int(dump_only=True)
    subtotal = fields.Float(dump_only=True)
    total = fields.Float(dump_only=True)
    discount = fields.Float(dump_only=True)
