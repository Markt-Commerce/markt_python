from marshmallow import Schema, fields, validate, ValidationError
from app.libs.schemas import PaginationSchema
from .models import ProductStatus


class ProductVariantSchema(Schema):
    name = fields.Str(required=True)
    options = fields.Dict(required=True)


class ProductCreateSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=2, max=100))
    description = fields.Str()
    price = fields.Float(required=True, validate=validate.Range(min=0.01))
    compare_at_price = fields.Float(validate=validate.Range(min=0.01))
    stock = fields.Int(validate=validate.Range(min=0))
    sku = fields.Str()
    barcode = fields.Str()
    weight = fields.Float()
    status = fields.Enum(ProductStatus, by_value=True)
    variants = fields.List(fields.Nested(ProductVariantSchema))
    category_ids = fields.List(fields.Int())
    tag_ids = fields.List(fields.Int())


class ProductUpdateSchema(ProductCreateSchema):
    class Meta:
        partial = True


class ProductSchema(ProductCreateSchema):
    id = fields.Str(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
    seller_id = fields.Int(dump_only=True)
    view_count = fields.Int(dump_only=True)
    like_count = fields.Int(dump_only=True)
    comment_count = fields.Int(dump_only=True)


class ProductSearchSchema(Schema):
    search = fields.Str(required=False)
    min_price = fields.Float(required=False)
    max_price = fields.Float(required=False)
    category_id = fields.Int(required=False)
    in_stock = fields.Bool(required=False)
    sort_by = fields.Str(
        required=False,
        validate=validate.OneOf(["newest", "popular", "price_asc", "price_desc"]),
    )


class ProductSearchResultSchema(Schema):
    products = fields.List(fields.Nested(ProductSchema))
    pagination = fields.Nested(PaginationSchema)


class ProductSimpleSchema(Schema):
    name = fields.Str()
    # price = fields.Float()


class BulkProductResultSchema(Schema):
    success = fields.List(fields.Dict(), required=True)
    errors = fields.List(fields.Dict(), required=True)
