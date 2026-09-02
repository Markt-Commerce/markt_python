"""Gamification REST endpoints (spec 5.5).

Session auth via Flask-Login; Marshmallow schemas drive the OpenAPI contract.
Importing `events` here wires the domain-signal handlers when the blueprint
loads.
"""

import logging

from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import current_user

from app.libs.decorators import login_required

from . import services
from . import events  # noqa: F401 - importing registers signal handlers
from .schemas import (
    GamMeSchema,
    GamificationProfileSchema,
    PointsHistoryResponseSchema,
    HistoryQueryArgs,
    LeaderboardResponseSchema,
    LeaderboardQueryArgs,
    BadgeCatalogResponseSchema,
    UserBadgesResponseSchema,
    TierConfigSchema,
    PreferencesUpdateSchema,
    PreferencesResponseSchema,
)

logger = logging.getLogger(__name__)

bp = Blueprint(
    "gamification",
    __name__,
    description="Points, tiers, badges and leaderboard",
    url_prefix="/gamification",
)


@bp.route("/me")
class MyGamification(MethodView):
    @login_required
    @bp.response(200, GamMeSchema)
    def get(self):
        """Current user's stats, tier, badge count and weekly rank."""
        return services.get_me(current_user.id)


@bp.route("/me/preferences")
class MyPreferences(MethodView):
    @login_required
    @bp.arguments(PreferencesUpdateSchema)
    @bp.response(200, PreferencesResponseSchema)
    def patch(self, data):
        """Toggle leaderboard opt-out and similar settings."""
        return services.set_preferences(
            current_user.id, opt_out_leaderboard=data.get("opt_out_leaderboard")
        )


@bp.route("/users/<user_id>/profile")
class PublicProfile(MethodView):
    @bp.response(200, GamificationProfileSchema)
    def get(self, user_id):
        """Public gamification profile: badges, tier, lifetime points."""
        return services.get_public_profile(user_id)


@bp.route("/users/<user_id>/badges")
class UserBadges(MethodView):
    @bp.response(200, UserBadgesResponseSchema)
    def get(self, user_id):
        """Badges held by a user, with progress on locked ones."""
        return services.get_user_badges(user_id)


@bp.route("/points/history")
class PointsHistory(MethodView):
    @login_required
    @bp.arguments(HistoryQueryArgs, location="query")
    @bp.response(200, PointsHistoryResponseSchema)
    def get(self, args):
        """Paginated ledger for the current user (cursor by ledger id)."""
        return services.get_points_history(
            current_user.id, cursor=args.get("cursor"), limit=args.get("limit", 20)
        )


@bp.route("/leaderboard")
class Leaderboard(MethodView):
    @login_required
    @bp.arguments(LeaderboardQueryArgs, location="query")
    @bp.response(200, LeaderboardResponseSchema)
    def get(self, args):
        """Ranked list for a scope/period with the current user's row pinned."""
        return services.get_leaderboard(
            scope=args["scope"],
            period=args["period"],
            limit=args.get("limit", 50),
            cursor=args.get("cursor"),
            user_id=current_user.id,
        )


@bp.route("/badges")
class BadgeCatalog(MethodView):
    @bp.response(200, BadgeCatalogResponseSchema)
    def get(self):
        """Full active badge catalog."""
        return {"items": services.get_badge_catalog()}


@bp.route("/tiers")
class Tiers(MethodView):
    @bp.response(200, TierConfigSchema(many=True))
    def get(self):
        """Tier configuration for client-side display."""
        return services.get_tiers()
