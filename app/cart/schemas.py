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
    use_saved_address = fields.Bool(missing=False)
    idempotency_key = fields.Str(
        allow_none=True
    )  # Optional idempotency key for retry safety
    # From POST /delivery/quote. Optional: clients that do not send one get
    # the flat-rate estimate, so older app versions keep working. When it is
    # present the buyer has been shown a real price and the order is held to
    # exactly that number.
    #: Check out only this shop's items. A basket spanning several shops is
    #: several orders, one per shop; the app shows them as separate cards and
    #: sends whichever was tapped. Omit to check out everything, which only
    #: works when the basket has one shop in it.
    seller_id = fields.Int(allow_none=True)
    delivery_quote_id = fields.Str(allow_none=True)
    # Only meaningful alongside a quote. The buyer asking to share a run with
    # other orders going the same way; never inferred on their behalf.
    batch_opt_in = fields.Bool(missing=False)
    #: A discount this shop offered the buyer in chat. Scoped to the shop being
    #: bought from and spent only if the order is actually created, so an
    #: abandoned checkout leaves the offer usable.
    discount_id = fields.Int(allow_none=True)


class CheckoutResponseSchema(Schema):
    """Full order summary returned after checkout."""

    order_id = fields.Str(required=True)
    order_number = fields.Str(allow_none=True)
    status = fields.Str(required=True)
    subtotal = fields.Float(required=True)
    shipping_fee = fields.Float(required=True)
    #: Always 0 -- Phase 0 defers VAT. Kept on the response because orders
    #: created before that decision carry a real figure.
    tax = fields.Float(required=True)
    #: 11.3. Null on orders created before this flow charged it.
    service_fee = fields.Float(allow_none=True)
    discount = fields.Float(required=True)
    total = fields.Float(required=True)
    shipping_address = fields.Dict(required=True)
    message = fields.Str()


class CartSummarySchema(Schema):
    """Schema for cart summary"""

    item_count = fields.Int(dump_only=True)
    subtotal = fields.Float(dump_only=True)
    total = fields.Float(dump_only=True)
    discount = fields.Float(dump_only=True)


class CartGroupSchema(Schema):
    """One shop's worth of the basket -- what will become one order.

    Carries its own subtotal and item count because each group checks out
    separately; a single cart-wide total would be a number the buyer can
    never actually pay.
    """

    seller_id = fields.Int(allow_none=True)
    shop_name = fields.Str(allow_none=True)
    shop_slug = fields.Str(allow_none=True)
    banner_url = fields.Str(allow_none=True)
    item_count = fields.Int()
    subtotal = fields.Float()
    items = fields.Nested(CartItemSchema, many=True)


class GroupedCartSchema(Schema):
    groups = fields.Nested(CartGroupSchema, many=True)
    #: More than one means the buyer has to check out more than once. Worth
    #: saying plainly rather than leaving them to count the cards.
    group_count = fields.Int()
    total_items = fields.Int()
