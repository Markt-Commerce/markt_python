from marshmallow import Schema, fields, validate
from app.libs.schemas import PaginationSchema
from app.products.schemas import ProductSimpleSchema, ProductVariantSchema
from app.users.schemas import BuyerSimpleSchema
from .events import OrderEventType, ActorType
from .models import OrderStatus, OrderItem


class OrderItemSchema(Schema):
    product_id = fields.Str(required=True)
    variant_id = fields.Int(required=False)
    quantity = fields.Int(required=True)
    price = fields.Float(required=True)
    seller_id = fields.Int(dump_only=True)
    status = fields.Enum(OrderItem.Status, by_value=True, dump_only=True)
    # An order item used to carry only a product_id, so any client rendering a
    # list of orders had to fetch each product separately just to show a name
    # and a thumbnail -- one request per line. The relationship already existed;
    # it was simply never exposed.
    product = fields.Nested(ProductSimpleSchema, dump_only=True)


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
    # For responses, serialize ORM relationship via helper dict on model
    shipping_address = fields.Dict(dump_only=True, attribute="shipping_address_dict")
    items = fields.Nested(lambda: OrderItemSchema(many=True), dump_only=True)


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
    shipping_address = fields.Dict(dump_only=True, attribute="shipping_address_dict")


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
    order_id = fields.Str()
    order_number = fields.Str(allow_none=True)
    status = fields.Str()
    timeline = fields.List(fields.Dict())
    shipping_address = fields.Dict(allow_none=True)
    items = fields.List(fields.Dict())
    shipment = fields.Dict(allow_none=True)
    delivery = fields.Dict(allow_none=True)


class OrderCancelSchema(Schema):
    reason = fields.Str(allow_none=True)


class OrderCancelResponseSchema(Schema):
    order_id = fields.Str()
    status = fields.Str()
    cancelled_at = fields.DateTime(allow_none=True)
    cancel_reason = fields.Str(allow_none=True)


class DeliveryWaitChoiceSchema(Schema):
    """10.3: the buyer's response to the thin-volume delivery prompt."""

    choice = fields.Str(required=True, validate=validate.OneOf(["wait", "pay_now"]))
    # Only meaningful for "wait" -- consent to being charged the
    # single-drop rate if the run still hasn't filled by cutoff.
    fallback_consent = fields.Bool(load_default=False)


class DeliveryWaitChoiceResponseSchema(Schema):
    order_id = fields.Str()
    choice = fields.Str()
    fallback_consent = fields.Bool()
    refund_amount = fields.Float()


class OrderReturnRequestSchema(Schema):
    reason = fields.Str(required=True, validate=validate.Length(min=3))


class OrderReturnResponseSchema(Schema):
    id = fields.Str()
    order_id = fields.Str()
    status = fields.Str()
    reason = fields.Str()
    refund_amount = fields.Float(allow_none=True)
    seller_notes = fields.Str(allow_none=True)
    created_at = fields.DateTime()


class OrderReturnActionSchema(Schema):
    seller_notes = fields.Str(allow_none=True)


class OrderItemStatusUpdateSchema(Schema):
    status = fields.Enum(OrderItem.Status, by_value=True, required=True)


class ReviewSchema(Schema):
    pass


class OrderEventSchema(Schema):
    """14.2 / 15: buyer-facing fulfilment-history entry."""

    id = fields.Int(dump_only=True)
    order_item_id = fields.Int(dump_only=True, allow_none=True)
    event_type = fields.Enum(OrderEventType, by_value=True, dump_only=True)
    actor_type = fields.Enum(ActorType, by_value=True, dump_only=True)
    metadata = fields.Dict(dump_only=True, attribute="event_metadata")
    created_at = fields.DateTime(dump_only=True)
