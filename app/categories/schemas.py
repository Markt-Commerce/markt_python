from marshmallow import Schema, fields, validate
from app.libs.schemas import PaginationSchema


class CategorySchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str(required=True)
    description = fields.Str()
    slug = fields.Str()
    image_url = fields.Str()
    is_active = fields.Bool()
    parent_id = fields.Int()


class CategoryTreeSchema(Schema):
    id = fields.Int()
    name = fields.Str()
    slug = fields.Str()
    image_url = fields.Str()
    children = fields.List(fields.Nested(lambda: CategoryTreeSchema()))


class CategoryCreateSchema(Schema):
    name = fields.Str(required=True)
    description = fields.Str()
    parent_id = fields.Int()
    is_active = fields.Bool()


class TagSchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str(required=True)
    slug = fields.Str()
    description = fields.Str()


class CategoryProductsSchema(Schema):
    category = fields.Nested(CategorySchema)
    products = fields.List(fields.Nested("ProductSchema"))
    pagination = fields.Nested(PaginationSchema)
