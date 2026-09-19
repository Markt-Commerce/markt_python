"""Trust & safety endpoints: report content, block users.

Required by App Store Review Guideline 1.2 for apps carrying user-generated
content -- alongside content filtering and published contact details, which
live outside this module.
"""

from flask.views import MethodView
from flask_login import current_user
from flask_smorest import Blueprint, abort

from app.libs.decorators import login_required, admin_required
from app.libs.errors import APIError

from .schemas import (
    BlockedListSchema,
    BlockResponseSchema,
    ContentReportCreateSchema,
    ContentReportResponseSchema,
    ReportResolveResponseSchema,
    ReportResolveSchema,
)
from .services import ModerationService

bp = Blueprint(
    "moderation",
    __name__,
    description="Content reporting and user blocking",
    url_prefix="/moderation",
)


@bp.route("/reports")
class ContentReports(MethodView):
    @login_required
    @bp.arguments(ContentReportCreateSchema)
    @bp.response(201, ContentReportResponseSchema)
    def post(self, data):
        """Report a post, product, comment, chat message or user."""
        try:
            return ModerationService.report_content(
                current_user.id,
                data["content_type"],
                data["content_id"],
                data["reason"],
                data.get("details"),
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/reports/<report_id>/resolve")
class ResolveReport(MethodView):
    @login_required
    @admin_required
    @bp.arguments(ReportResolveSchema)
    @bp.response(200, ReportResolveResponseSchema)
    def post(self, data, report_id):
        """Close out a report (admin only)."""
        try:
            return ModerationService.resolve_report(
                report_id, current_user.id, data["status"], data.get("note")
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/blocks")
class BlockList(MethodView):
    @login_required
    @bp.response(200, BlockedListSchema)
    def get(self):
        """People the signed-in user has blocked.

        Only outgoing blocks -- listing who blocked *you* would leak it.
        """
        return {"blocked": ModerationService.list_blocked(current_user.id)}


@bp.route("/blocks/<user_id>")
class BlockUser(MethodView):
    @login_required
    @bp.response(200, BlockResponseSchema)
    def post(self, user_id):
        """Block a user. Also severs any follow in either direction."""
        try:
            return ModerationService.block_user(current_user.id, user_id)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @bp.response(200, BlockResponseSchema)
    def delete(self, user_id):
        """Unblock a user. Does not restore the previous follow."""
        try:
            return ModerationService.unblock_user(current_user.id, user_id)
        except APIError as e:
            abort(e.status_code, message=e.message)
