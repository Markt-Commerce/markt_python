from marshmallow import Schema, fields, validate
from app.libs.schemas import PaginationSchema
from app.products.schemas import ProductSimpleSchema, ProductVariantSchema
from app.users.schemas import BuyerSimpleSchema
from .models import OrderStatus, OrderItem


class OrderItemSchema(Schema):
    product_id = fields.Str(required=True)
    variant_id = fields.Int(required=False)
    quantity = fields.Int(required=True)
    price = fields.Float(required=True)
    seller_id = fields.Int(dump_only=True)
    status = fields.Enum(OrderItem.Status, by_value=True, dump_only=True)


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


class OrderPaginationSchema(Schema):
    orders = fields.List(fields.Nested(OrderSchema))
    pagination = fields.Nested(PaginationSchema)


# For buyers - shows complete order
class BuyerOrderSchema(OrderCreateSchema):
    id = fields.Str(dump_only=True)
    order_number = fields.Str(dump_only=True)
    status = fields.Enum(OrderStatus, by_value=True, dump_only=True)
    subtotal = fields.Float(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    items = fields.Nested(lambda: OrderItemSchema(many=True), dump_only=True)


# For sellers - shows individual order items
class SellerOrderItemSchema(Schema):
    id = fields.Int(dump_only=True)
    order_id = fields.Str(dump_only=True)
    product = fields.Nested(lambda: ProductSimpleSchema())
    variant = fields.Nested(lambda: ProductVariantSchema())
    quantity = fields.Int(dump_only=True)
    price = fields.Float(dump_only=True)
    status = fields.Enum(OrderItem.Status, by_value=True, dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    order = fields.Nested(lambda: OrderSimpleSchema())


class OrderSimpleSchema(Schema):
    id = fields.Str(dump_only=True)
    order_number = fields.Str(dump_only=True)
    buyer = fields.Nested(lambda: BuyerSimpleSchema())
    created_at = fields.DateTime(dump_only=True)


class SellerOrderResponseSchema(Schema):
    items = fields.Nested(SellerOrderItemSchema(many=True))
    pagination = fields.Nested(PaginationSchema())


class TrackingSchema(Schema):
    pass


class ReviewSchema(Schema):
    pass
