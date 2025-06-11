# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, current_user
from marshmallow import fields

# project imports
from app.libs.schemas import PaginationQueryArgs

# app imports
from .schemas import (
    NotificationSchema,
    NotificationPaginationSchema,
    UnreadCountSchema,
    MarkAsReadRequestSchema,
    MarkAsReadResponseSchema,
)
from .services import NotificationService

bp = Blueprint(
    "notifications",
    __name__,
    description="Notification operations",
    url_prefix="/notifications",
)


@bp.route("/")
class NotificationList(MethodView):
    @login_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, NotificationPaginationSchema)
    def get(self, args):
        """Get user notifications"""
        return NotificationService.get_user_notifications(
            current_user.id, page=args.get("page", 1), per_page=args.get("per_page", 20)
        )


@bp.route("/unread/count")
class UnreadCount(MethodView):
    @login_required
    @bp.response(200, UnreadCountSchema)
    def get(self):
        """Get count of unread notifications"""
        notifications = NotificationService.get_user_notifications(
            current_user.id, page=1, per_page=1, unread_only=True
        )
        return {"count": notifications["pagination"]["total_items"]}


@bp.route("/mark-read")
class MarkAsRead(MethodView):
    @login_required
    @bp.arguments(MarkAsReadRequestSchema, location="json")
    @bp.response(200, MarkAsReadResponseSchema)
    def post(self, data):
        """Mark notifications as read"""
        updated = NotificationService.mark_as_read(
            current_user.id, data.get("notification_ids")
        )
        return {"updated": updated}
