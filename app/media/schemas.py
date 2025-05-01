from marshmallow import Schema, fields
from .models import MediaType


class MediaSchema(Schema):
    id = fields.Int(dump_only=True)
    url = fields.Method("get_url")
    alt_text = fields.Str()
    media_type = fields.Enum(MediaType)

    def get_url(self, obj):
        return f"https://{self.context['cdn_domain']}/{obj.storage_key}"


class ProductImageSchema(Schema):
    id = fields.Int(dump_only=True)
    media = fields.Nested(MediaSchema)
    is_featured = fields.Bool()
    sort_order = fields.Int()
