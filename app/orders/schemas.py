from marshmallow import Schema, fields, validate
from .models import OrderStatus


class OrderItemSchema(Schema):
    product_id = fields.Int(required=True)
    quantity = fields.Int(required=True)
    price = fields.Float(required=True)


class OrderSchema(Schema):
    id = fields.Int(dump_only=True)
    user_id = fields.Int(required=True)
    total = fields.Float(required=True)
    status = fields.Enum(OrderStatus)
    items = fields.List(fields.Nested(OrderItemSchema))
    shipping_address = fields.Dict()
    created_at = fields.DateTime(dump_only=True)


class OrderCreateSchema(OrderSchema):
    class Meta:
        exclude = ("id", "status", "created_at")


class TrackingSchema(Schema):
    pass


class ReviewSchema(Schema):
    pass
