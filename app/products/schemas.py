from marshmallow import EXCLUDE, Schema, fields, validate, ValidationError
from app.libs.schemas import PaginationSchema
from app.categories.schemas import CategorySchema
from app.users.schemas import SellerSimpleSchema
from app.media.schemas import ProductImageSchema
from .models import ProductStatus


class ProductVariantSchema(Schema):
    name = fields.Str(required=True)
    options = fields.Dict(required=True)


class ProductCreateSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=2, max=100))
    description = fields.Str()
    price = fields.Float(required=True, validate=validate.Range(min=0.01))
    compare_at_price = fields.Float(validate=validate.Range(min=0.01))
    cost_per_item = fields.Float(validate=validate.Range(min=0.01))
    stock = fields.Int(validate=validate.Range(min=0))
    sku = fields.Str()
    barcode = fields.Str()
    weight = fields.Float()
    status = fields.Enum(ProductStatus, by_value=True)
    variants = fields.List(fields.Nested(ProductVariantSchema))
    category_ids = fields.List(fields.Int())
    tag_ids = fields.List(fields.Int())
    product_metadata = fields.Dict()
    media_ids = fields.List(
        fields.Int(), description="List of media IDs to link to product"
    )


class ProductUpdateSchema(Schema):
    name = fields.Str(validate=validate.Length(min=2, max=100))
    description = fields.Str()
    price = fields.Float(validate=validate.Range(min=0.01))
    compare_at_price = fields.Float(validate=validate.Range(min=0.01))
    cost_per_item = fields.Float(validate=validate.Range(min=0.01))
    stock = fields.Int(validate=validate.Range(min=0))
    sku = fields.Str()
    barcode = fields.Str()
    weight = fields.Float()
    status = fields.Enum(ProductStatus, by_value=True)
    variants = fields.List(fields.Nested(ProductVariantSchema))
    category_ids = fields.List(fields.Int())
    tag_ids = fields.List(fields.Int())
    product_metadata = fields.Dict()
    media_ids = fields.List(
        fields.Int(), description="List of media IDs to link to product"
    )


class ProductSchema(ProductCreateSchema):
    id = fields.Str(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
    seller_id = fields.Int(dump_only=True)
    view_count = fields.Int(dump_only=True)
    average_rating = fields.Float(dump_only=True)
    review_count = fields.Int(dump_only=True)
    categories = fields.Method("get_categories", dump_only=True)

    def get_categories(self, obj):
        """Extract category data from ProductCategory objects"""
        if hasattr(obj, "categories") and obj.categories:
            from app.categories.schemas import CategorySchema

            category_schema = CategorySchema()
            return [
                category_schema.dump(product_category.category)
                for product_category in obj.categories
                if product_category.category
            ]
        return []

    def get_seller_user_info(self, obj):
        """Extract seller's user information for messaging functionality"""
        if (
            hasattr(obj, "seller")
            and obj.seller
            and hasattr(obj.seller, "user")
            and obj.seller.user
        ):
            return {
                "id": obj.seller.user.id,
                "username": obj.seller.user.username,
                "profile_picture": obj.seller.user.profile_picture,
            }
        return None

    images = fields.List(fields.Nested("ProductImageSchema"), dump_only=True)
    seller = fields.Nested("SellerSimpleSchema", dump_only=True)
    seller_user = fields.Method("get_seller_user_info", dump_only=True)


class ProductSearchSchema(Schema):
    search = fields.Str(required=False)
    min_price = fields.Float(required=False)
    max_price = fields.Float(required=False)
    in_stock = fields.Bool(required=False)
    sort_by = fields.Str(
        required=False,
        validate=validate.OneOf(["newest", "popular", "price_asc", "price_desc"]),
    )


class SellerProductQueryArgs(Schema):
    """Query arguments for GET /products/seller/my-products.

    The route used the generic PaginationQueryArgs, which carries a `search`
    field the service never received — so the seller dashboard did its own
    filtering over whichever page it was holding. That is fine while the
    client asks for 50 products and calls it the whole inventory, and wrong
    the moment it pages properly.
    """

    class Meta:
        unknown = EXCLUDE

    page = fields.Int(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Int(load_default=20, validate=validate.Range(min=1, max=100))
    search = fields.Str(description="Matches product name or SKU")
    status = fields.Str(
        validate=validate.OneOf([s.value for s in ProductStatus]),
        description="Filter by product status",
    )
    low_stock = fields.Bool(
        load_default=False, description="Only products below the low-stock threshold"
    )


class ProductSearchResultSchema(Schema):
    items = fields.List(fields.Nested(ProductSchema))
    pagination = fields.Nested(PaginationSchema)


class ProductSimpleSchema(Schema):
    """The minimum needed to render a product in a list row.

    Carried only `name`, which is why an order row could print the product's
    title but not its thumbnail -- the mobile order list fell back to a
    "No image" placeholder on every line, and the order *detail* screen worked
    around it by fetching each product separately, one request per item.
    """

    id = fields.Str(dump_only=True)
    name = fields.Str()
    image_url = fields.Method("get_image_url", dump_only=True)

    def get_image_url(self, obj):
        """First image, or None. Never raises -- a missing thumbnail must not
        take down the order list it appears in."""
        try:
            images = getattr(obj, "images", None) or []
            if not images:
                return None
            media = getattr(images[0], "media", None)
            return media.get_url() if media else None
        except Exception:
            return None


class BulkProductResultSchema(Schema):
    success = fields.List(fields.Dict(), required=True)
    errors = fields.List(fields.Dict(), required=True)


class ProductShareLinkSchema(Schema):
    """Canonical links for sharing a product.

    Both are returned because a share sheet has no idea whether the recipient
    has the app: `deep_link` opens it directly, `web_url` is the fallback that
    works for anyone and can itself bounce into the app.
    """

    product_id = fields.Str()
    product_name = fields.Str()
    deep_link = fields.Str()
    web_url = fields.Str()
    message = fields.Str()
