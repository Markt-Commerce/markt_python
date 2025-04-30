from marshmallow import Schema, fields


class PaginationQueryArgs(Schema):
    page = fields.Int(required=False, default=1)
    per_page = fields.Int(required=False, default=20)
    search = fields.Str(required=False)
    sort = fields.Str(required=False)
    filters = fields.Dict(required=False)


class PaginationSchema(Schema):
    page = fields.Int()
    per_page = fields.Int()
    total_items = fields.Int()
    total_pages = fields.Int()
