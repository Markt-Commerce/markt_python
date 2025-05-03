from marshmallow import Schema, fields, validate
from .models import OrderStatus


class OrderItemSchema(Schema):
    product_id = fields.Str(required=True)
    variant_id = fields.Int(required=False)
    quantity = fields.Int(required=True)
    price = fields.Float(required=True)


class OrderCreateSchema(Schema):
    cart_id = fields.Int(required=True)
    shipping_address = fields.Dict(required=True)
    payment_method = fields.Str(required=True)
    customer_note = fields.Str()


class OrderSchema(OrderCreateSchema):
    id = fields.Str(dump_only=True)
    order_number = fields.Str(dump_only=True)
    buyer_id = fields.Int(dump_only=True)
    seller_id = fields.Int(dump_only=True)
    status = fields.Enum(OrderStatus, by_value=True, dump_only=True)
    subtotal = fields.Float(dump_only=True)
    shipping_fee = fields.Float(dump_only=True)
    tax = fields.Float(dump_only=True)
    discount = fields.Float(dump_only=True)
    total = fields.Float(dump_only=True)
    created_at = fields.DateTime(dump_only=True)


class TrackingSchema(Schema):
    pass


class ReviewSchema(Schema):
    pass
