from marshmallow import Schema, fields, validate

from .models import ReportedContentType, ReportReason, ReportStatus

CONTENT_TYPES = [c.value for c in ReportedContentType]
REASONS = [r.value for r in ReportReason]
STATUSES = [s.value for s in ReportStatus]


class ContentReportCreateSchema(Schema):
    content_type = fields.Str(required=True, validate=validate.OneOf(CONTENT_TYPES))
    content_id = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    reason = fields.Str(required=True, validate=validate.OneOf(REASONS))
    details = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(max=2000),
        metadata={"description": "Optional free text from the reporter"},
    )


class ContentReportResponseSchema(Schema):
    report_id = fields.Str(allow_none=True)
    status = fields.Str()
    already_reported = fields.Bool()
    message = fields.Str()


class BlockResponseSchema(Schema):
    blocked = fields.Bool()
    user_id = fields.Str()


class BlockedUserSchema(Schema):
    user_id = fields.Str()
    username = fields.Str()
    profile_picture = fields.Str(allow_none=True)
    blocked_at = fields.Str(allow_none=True)


class BlockedListSchema(Schema):
    blocked = fields.List(fields.Nested(BlockedUserSchema))


class ReportResolveSchema(Schema):
    status = fields.Str(required=True, validate=validate.OneOf(STATUSES))
    note = fields.Str(
        required=False, allow_none=True, validate=validate.Length(max=500)
    )


class ReportResolveResponseSchema(Schema):
    report_id = fields.Str()
    status = fields.Str()
    reviewed_at = fields.Str()
