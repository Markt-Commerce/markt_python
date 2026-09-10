from marshmallow import Schema, fields, validate, EXCLUDE


class BrowseLocationSchema(Schema):
    """A browse location as the app sees it."""

    latitude = fields.Float()
    longitude = fields.Float()
    label = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)
    lga = fields.Str(allow_none=True)


class SetBrowseLocationSchema(Schema):
    """PUT /location/browse.

    `guest_id` lets a signed-out user keep a chosen area. It is a device-scoped
    opaque id, never a credential -- the worst a forged one can do is read or
    change another guest's *browse preference*, which contains no personal data
    and no purchasing power.
    """

    class Meta:
        unknown = EXCLUDE

    latitude = fields.Float(required=True, validate=validate.Range(-90, 90))
    longitude = fields.Float(required=True, validate=validate.Range(-180, 180))
    label = fields.Str(load_default=None, allow_none=True)
    state = fields.Str(load_default=None, allow_none=True)
    lga = fields.Str(load_default=None, allow_none=True)
    guest_id = fields.Str(load_default=None, allow_none=True)


class NearbyQueryArgs(Schema):
    class Meta:
        unknown = EXCLUDE

    latitude = fields.Float(load_default=None)
    longitude = fields.Float(load_default=None)
    limit = fields.Int(load_default=20, validate=validate.Range(1, 50))
    cursor = fields.Str(load_default=None, allow_none=True)
    guest_id = fields.Str(load_default=None, allow_none=True)


class NearbyProductSchema(Schema):
    id = fields.Str()
    name = fields.Str()
    price = fields.Float()
    seller_id = fields.Int()
    """Straight-line km from the browse location. Null when the seller has no
    shop location, or when the nationwide rung produced the row."""
    distance_km = fields.Float(allow_none=True)


class NearbyFeedSchema(Schema):
    items = fields.List(fields.Nested(NearbyProductSchema))
    # Which rung of the ladder answered: nearby | widened | regional |
    # nationwide. The app shows this so a distant result is never presented as
    # if it were close.
    scope = fields.Str()
    radius_km = fields.Float(allow_none=True)
    next_cursor = fields.Str(allow_none=True)
