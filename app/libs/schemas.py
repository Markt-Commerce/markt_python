from marshmallow import Schema, fields, validate, ValidationError
import json


class PaginationQueryArgs(Schema):
    page = fields.Int(required=False, default=1)
    per_page = fields.Int(required=False, default=20)
    search = fields.Str(required=False)
    sort = fields.Str(required=False)
    filters = fields.Str(required=False)


class PaginationSchema(Schema):
    page = fields.Int()
    per_page = fields.Int()
    total_items = fields.Int()
    total_pages = fields.Int()


class FilterField(Schema):
    field = fields.Str(required=True)
    operator = fields.Str(required=False, default="eq")
    value = fields.Raw(required=True)


class FiltersSchema(Schema):
    filters = fields.Dict(keys=fields.Str(), values=fields.Raw(), required=False)

    @staticmethod
    def parse_filters(filters_str):
        try:
            if not filters_str:
                return {}
            if isinstance(filters_str, str):
                return json.loads(filters_str)
            return filters_str
        except json.JSONDecodeError:
            raise ValidationError("Invalid filters format")
