from marshmallow import Schema, fields


class MarketSchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str(dump_only=True)
    slug = fields.Str(dump_only=True)
    latitude = fields.Float(dump_only=True, allow_none=True)
    longitude = fields.Float(dump_only=True, allow_none=True)
    is_active = fields.Bool(dump_only=True)
    seller_count = fields.Int(dump_only=True)


class MarketListSchema(Schema):
    markets = fields.List(fields.Nested(MarketSchema))
