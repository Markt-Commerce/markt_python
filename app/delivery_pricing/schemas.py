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
    #: Whether sharing a run is on offer at all. The client cannot know --
    #: it is a deployment flag -- and offering a choice that does not exist
    #: is worse than not offering it.
    batch_available = fields.Method("get_batch_available", dump_only=True)

    def get_batch_available(self, obj):
        from .batch import batch_enabled

        return batch_enabled()


class ServiceabilityQuerySchema(Schema):
    class Meta:
        unknown = EXCLUDE

    latitude = fields.Float(required=True, validate=validate.Range(-90, 90))
    longitude = fields.Float(required=True, validate=validate.Range(-180, 180))


class ServiceabilityResultSchema(Schema):
    serviceable = fields.Bool()
    city = fields.Str(allow_none=True)
    zone = fields.Str(allow_none=True)


class JobStatusUpdateSchema(Schema):
    """What a logistics provider posts when a parcel moves.

    Documented for the partner in docs/LOGISTICS_API_CONTRACT.md. `status` is
    deliberately a free string rather than an enum: a provider's vocabulary is
    theirs, we map synonyms on our side, and a word we do not recognise is
    logged and ignored rather than rejected with an error they would only
    retry harder at.
    """

    class Meta:
        unknown = EXCLUDE

    status = fields.Str(required=True)
    occurred_at = fields.DateTime(required=False, allow_none=True)
    reason = fields.Str(required=False, allow_none=True)


class JobStatusAckSchema(Schema):
    applied = fields.Bool()
    state = fields.Str(allow_none=True)


class CombinedPickupShareSchema(Schema):
    seller_id = fields.Int()
    charged_minor = fields.Int()
    solo_fee_minor = fields.Int()
    saved_minor = fields.Int()


class CombinedQuoteSchema(Schema):
    """What one rider collecting from several nearby shops would cost."""

    available = fields.Bool()
    #: Why not, when it isn't. The client says something specific rather than
    #: hiding the option with no explanation.
    reason = fields.Str(allow_none=True)
    combined_fee_minor = fields.Int(allow_none=True)
    separate_fee_minor = fields.Int(allow_none=True)
    saved_minor = fields.Int(allow_none=True)
    shares = fields.Nested(CombinedPickupShareSchema, many=True)


class CombinedQuoteRequestSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    seller_ids = fields.List(
        fields.Int(), required=True, validate=validate.Length(min=2, max=5)
    )
    dropoff_latitude = fields.Float(required=True, validate=validate.Range(-90, 90))
    dropoff_longitude = fields.Float(required=True, validate=validate.Range(-180, 180))
