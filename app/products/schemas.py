from marshmallow import Schema, fields, validate, ValidationError
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


class ProductUpdateSchema(ProductCreateSchema):
    class Meta:
        partial = True


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

    images = fields.List(fields.Nested("ProductImageSchema"), dump_only=True)
    seller = fields.Nested("SellerSimpleSchema", dump_only=True)


class ProductSearchSchema(Schema):
    search = fields.Str(required=False)
    min_price = fields.Float(required=False)
    max_price = fields.Float(required=False)
    in_stock = fields.Bool(required=False)
    sort_by = fields.Str(
        required=False,
        validate=validate.OneOf(["newest", "popular", "price_asc", "price_desc"]),
    )


class ProductSearchResultSchema(Schema):
    items = fields.List(fields.Nested(ProductSchema))
    pagination = fields.Nested(PaginationSchema)


class ProductSimpleSchema(Schema):
    name = fields.Str()
    # price = fields.Float()


class BulkProductResultSchema(Schema):
    success = fields.List(fields.Dict(), required=True)
    errors = fields.List(fields.Dict(), required=True)
