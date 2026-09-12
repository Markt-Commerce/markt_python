from marshmallow import EXCLUDE, Schema, fields, validate


class QuoteRequestSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    seller_id = fields.Int(required=True)
    dropoff_latitude = fields.Float(required=True, validate=validate.Range(-90, 90))
    dropoff_longitude = fields.Float(required=True, validate=validate.Range(-180, 180))
    item_count = fields.Int(load_default=1, validate=validate.Range(min=1))
    total_weight_grams = fields.Int(load_default=0, validate=validate.Range(min=0))
    # "confirmed" once the buyer has moved or accepted the pin. Anything the
    # app derived on its own -- a reverse geocode, a saved landmark -- stays
    # approximate, and the client requires confirmation before paying.
    precision = fields.Str(
        load_default="approximate",
        validate=validate.OneOf(["approximate", "confirmed"]),
    )


class FeeLineSchema(Schema):
    label = fields.Str()
    amount_minor = fields.Int()


class BreakdownSchema(Schema):
    total_minor = fields.Int()
    lines = fields.List(fields.Nested(FeeLineSchema))


class QuoteSchema(Schema):
    id = fields.Str(dump_only=True)
    fee_minor = fields.Int(dump_only=True)
    breakdown = fields.Nested(BreakdownSchema, dump_only=True)
    distance_km = fields.Float(dump_only=True)
    precision = fields.Str(dump_only=True)
    expires_at = fields.DateTime(dump_only=True)
    strategy = fields.Str(dump_only=True)
    strategy_version = fields.Str(dump_only=True)


class ServiceabilityQuerySchema(Schema):
    class Meta:
        unknown = EXCLUDE

    latitude = fields.Float(required=True, validate=validate.Range(-90, 90))
    longitude = fields.Float(required=True, validate=validate.Range(-180, 180))


class ServiceabilityResultSchema(Schema):
    serviceable = fields.Bool()
    city = fields.Str(allow_none=True)
    zone = fields.Str(allow_none=True)
