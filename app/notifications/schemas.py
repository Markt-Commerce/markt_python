from marshmallow import Schema, fields, validate
from app.libs.schemas import PaginationSchema


class NotificationSchema(Schema):
    id = fields.Int(dump_only=True)
    type = fields.Str(dump_only=True)
    title = fields.Str(dump_only=True)
    message = fields.Str(dump_only=True)
    is_read = fields.Bool(dump_only=True)
    reference_type = fields.Str(dump_only=True)
    reference_id = fields.Str(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    metadata_ = fields.Dict(dump_only=True)


class NotificationPaginationSchema(Schema):
    items = fields.List(fields.Nested(NotificationSchema))
    pagination = fields.Nested(PaginationSchema)


class UnreadCountSchema(Schema):
    count = fields.Int()


class MarkAsReadRequestSchema(Schema):
    notification_ids = fields.List(fields.Int(), required=True)


class MarkAsReadResponseSchema(Schema):
    updated = fields.Int()
