from marshmallow import Schema, fields, validate
from .models import ProductStatus


class ProductSchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str(required=True, validate=validate.Length(min=2))
    description = fields.Str()
    price = fields.Float(required=True)
    stock_quantity = fields.Int()
    status = fields.Enum(ProductStatus)
    metadata = fields.Dict()
    seller_id = fields.Int(required=True)


class ProductCreateSchema(ProductSchema):
    class Meta:
        exclude = ("id", "status")


class ProductUpdateSchema(Schema):
    name = fields.Str(validate=validate.Length(min=2))
    description = fields.Str()
    price = fields.Float()
    stock_quantity = fields.Int()
    status = fields.Enum(ProductStatus)
