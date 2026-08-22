"""Marshmallow schemas for the gamification REST contract (spec 5.5).

Responses are built as plain dicts in services.py; these schemas shape the
OpenAPI output and serialise datetimes.
"""

from marshmallow import Schema, fields, validate

from .constants import LB_SCOPES, LB_PERIODS


# --- Shared -------------------------------------------------------------------
class TierSchema(Schema):
    key = fields.Str()
    name = fields.Str()
    stars = fields.Int()
    color_hex = fields.Str()
    progress_to_next = fields.Float()
    points_to_next_tier = fields.Int()


class WeeklyRankSchema(Schema):
    scope = fields.Str()
    rank = fields.Int()
    out_of = fields.Int()


class BadgeSchema(Schema):
    slug = fields.Str()
    name = fields.Str()
    description = fields.Str(allow_none=True)
    icon_url = fields.Str(allow_none=True)
    category = fields.Str(allow_none=True)
    audience = fields.Str()
    priority = fields.Int()


# --- GET /me ------------------------------------------------------------------
class GamMeSchema(Schema):
    user_id = fields.Str()
    lifetime_points = fields.Int()
    available_points = fields.Int()
    weekly_points = fields.Int()
    tier = fields.Nested(TierSchema)
    badges_earned = fields.Int()
    badges_total = fields.Int()
    weekly_rank = fields.Nested(WeeklyRankSchema, allow_none=True)
    opt_out_leaderboard = fields.Bool()


# --- GET /users/{id}/profile --------------------------------------------------
class PublicProfileSchema(Schema):
    user_id = fields.Str()
    lifetime_points = fields.Int()
    tier = fields.Nested(TierSchema)
    badges = fields.List(fields.Nested(BadgeSchema))


# --- GET /users/{id}/badges ---------------------------------------------------
class UserBadgeSchema(BadgeSchema):
    earned = fields.Bool()
    awarded_at = fields.DateTime(allow_none=True)
    progress = fields.Float()


class UserBadgesResponseSchema(Schema):
    items = fields.List(fields.Nested(UserBadgeSchema))


# --- GET /points/history ------------------------------------------------------
class PointsHistoryItemSchema(Schema):
    id = fields.Int()
    delta = fields.Int()
    reason = fields.Str()
    ref_type = fields.Str(allow_none=True)
    ref_id = fields.Str(allow_none=True)
    balance_after = fields.Int()
    created_at = fields.DateTime()


class PointsHistoryResponseSchema(Schema):
    items = fields.List(fields.Nested(PointsHistoryItemSchema))
    next_cursor = fields.Int(allow_none=True)


class HistoryQueryArgs(Schema):
    cursor = fields.Int(load_default=None, allow_none=True)
    limit = fields.Int(load_default=20, validate=validate.Range(min=1, max=100))


# --- GET /leaderboard ---------------------------------------------------------
class LeaderboardRowSchema(Schema):
    rank = fields.Int()
    user_id = fields.Str()
    points = fields.Int()
    username = fields.Str(allow_none=True)
    profile_picture = fields.Str(allow_none=True)
    tier = fields.Str(allow_none=True)
    stars = fields.Int(allow_none=True)


class LeaderboardRankSchema(Schema):
    scope = fields.Str()
    period = fields.Str()
    rank = fields.Int()
    points = fields.Int()
    out_of = fields.Int()


class LeaderboardResponseSchema(Schema):
    scope = fields.Str()
    period = fields.Str()
    items = fields.List(fields.Nested(LeaderboardRowSchema))
    next_cursor = fields.Int(allow_none=True)
    your_rank = fields.Nested(LeaderboardRankSchema, allow_none=True)


class LeaderboardQueryArgs(Schema):
    scope = fields.Str(load_default="global", validate=validate.OneOf(LB_SCOPES))
    period = fields.Str(load_default="weekly", validate=validate.OneOf(LB_PERIODS))
    limit = fields.Int(load_default=50, validate=validate.Range(min=1, max=100))
    cursor = fields.Int(load_default=None, allow_none=True)


# --- GET /tiers ---------------------------------------------------------------
class TierConfigSchema(Schema):
    tier = fields.Str()
    name = fields.Str()
    min_lifetime_points = fields.Int()
    color_hex = fields.Str()
    star_count = fields.Int()


# --- GET /badges --------------------------------------------------------------
class BadgeCatalogResponseSchema(Schema):
    items = fields.List(fields.Nested(BadgeSchema))


# --- PATCH /me/preferences ----------------------------------------------------
class PreferencesUpdateSchema(Schema):
    opt_out_leaderboard = fields.Bool(load_default=None, allow_none=True)


class PreferencesResponseSchema(Schema):
    opt_out_leaderboard = fields.Bool()
