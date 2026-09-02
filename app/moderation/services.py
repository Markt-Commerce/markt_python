"""Trust & safety services: reporting content and blocking users."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.exc import IntegrityError

from app.libs.errors import NotFoundError, ValidationError
from app.libs.session import session_scope

from .models import (
    ContentReport,
    ReportedContentType,
    ReportReason,
    ReportStatus,
    UserBlock,
)

logger = logging.getLogger(__name__)


class ModerationService:
    @staticmethod
    def _assert_content_exists(
        session, content_type: ReportedContentType, content_id: str
    ):
        """Reject reports against things that don't exist.

        Without this the queue fills with unactionable rows from stale clients
        and from anyone poking the endpoint with made-up ids.
        """
        from app.socials.models import Post, PostComment
        from app.products.models import Product
        from app.users.models import User

        if content_type == ReportedContentType.POST:
            exists = session.query(Post.id).filter_by(id=content_id).first()
        elif content_type == ReportedContentType.PRODUCT:
            exists = session.query(Product.id).filter_by(id=content_id).first()
        elif content_type == ReportedContentType.COMMENT:
            exists = session.query(PostComment.id).filter_by(id=content_id).first()
        elif content_type == ReportedContentType.USER:
            exists = session.query(User.id).filter_by(id=content_id).first()
        else:
            # Chat messages are private to the two participants; existence is
            # checked by the chat module's own access rules before we get here.
            exists = True

        if not exists:
            raise NotFoundError("The content you're reporting no longer exists")

    @staticmethod
    def report_content(
        reporter_id: str,
        content_type: str,
        content_id: str,
        reason: str,
        details: Optional[str] = None,
    ) -> Dict[str, Any]:
        """File a report. Idempotent per (reporter, content)."""
        try:
            ctype = ReportedContentType(content_type)
            creason = ReportReason(reason)
        except ValueError:
            raise ValidationError("Unknown content type or reason")

        with session_scope() as session:
            ModerationService._assert_content_exists(session, ctype, content_id)

            if ctype == ReportedContentType.USER and content_id == reporter_id:
                raise ValidationError("You cannot report yourself")

            existing = (
                session.query(ContentReport)
                .filter_by(
                    reporter_id=reporter_id,
                    content_type=ctype,
                    content_id=content_id,
                )
                .first()
            )
            if existing:
                # Already reported: report it back as accepted rather than as
                # an error. The user's intent is satisfied and telling them
                # "you already reported this" is the honest, calmer response.
                return {
                    "report_id": existing.id,
                    "status": existing.status.value,
                    "already_reported": True,
                    "message": "You've already reported this. Our team is reviewing it.",
                }

            report = ContentReport(
                reporter_id=reporter_id,
                content_type=ctype,
                content_id=content_id,
                reason=creason,
                details=(details or None),
                status=ReportStatus.PENDING,
            )
            session.add(report)
            try:
                session.flush()
            except IntegrityError:
                # Lost a race with the same user double-tapping.
                session.rollback()
                return {
                    "report_id": None,
                    "status": ReportStatus.PENDING.value,
                    "already_reported": True,
                    "message": "You've already reported this. Our team is reviewing it.",
                }

            logger.info(
                "Content reported: %s %s by %s (%s)",
                ctype.value,
                content_id,
                reporter_id,
                creason.value,
            )
            return {
                "report_id": report.id,
                "status": report.status.value,
                "already_reported": False,
                "message": "Thanks for letting us know. Our team will review this.",
            }

    # ---------------------------------------------------------------- blocks
    @staticmethod
    def block_user(blocker_id: str, blocked_id: str) -> Dict[str, Any]:
        if blocker_id == blocked_id:
            raise ValidationError("You cannot block yourself")

        from app.users.models import User

        with session_scope() as session:
            target = session.query(User).get(blocked_id)
            # getattr: deleted_at ships on the account-deletion branch. This
            # module must not require it to be merged first -- once it is, a
            # deleted account correctly reads as "not found" here too.
            if not target or getattr(target, "deleted_at", None) is not None:
                raise NotFoundError("User not found")

            existing = (
                session.query(UserBlock)
                .filter_by(blocker_id=blocker_id, blocked_id=blocked_id)
                .first()
            )
            if not existing:
                session.add(UserBlock(blocker_id=blocker_id, blocked_id=blocked_id))
                session.flush()

            # Blocking someone you follow (or who follows you) should sever it;
            # otherwise their content keeps arriving through the following feed.
            from app.socials.models import Follow

            session.query(Follow).filter(
                (
                    (Follow.follower_id == blocker_id)
                    & (Follow.followee_id == blocked_id)
                )
                | (
                    (Follow.follower_id == blocked_id)
                    & (Follow.followee_id == blocker_id)
                )
            ).delete(synchronize_session=False)

        return {"blocked": True, "user_id": blocked_id}

    @staticmethod
    def unblock_user(blocker_id: str, blocked_id: str) -> Dict[str, Any]:
        with session_scope() as session:
            session.query(UserBlock).filter_by(
                blocker_id=blocker_id, blocked_id=blocked_id
            ).delete(synchronize_session=False)
        return {"blocked": False, "user_id": blocked_id}

    @staticmethod
    def blocked_user_ids(user_id: Optional[str]) -> Set[str]:
        """Ids this user should not see content from, in either direction.

        Includes people who blocked *them* as well: if A blocks B, B should
        not be able to keep interacting with A through the feed either, which
        is what "block" means to the person who used it.
        """
        if not user_id:
            return set()
        with session_scope() as session:
            rows = (
                session.query(UserBlock.blocker_id, UserBlock.blocked_id)
                .filter(
                    (UserBlock.blocker_id == user_id)
                    | (UserBlock.blocked_id == user_id)
                )
                .all()
            )
        ids = set()
        for blocker_id, blocked_id in rows:
            ids.add(blocked_id if blocker_id == user_id else blocker_id)
        return ids

    @staticmethod
    def list_blocked(user_id: str) -> List[Dict[str, Any]]:
        """Only people this user actively blocked -- not people who blocked
        them. Surfacing the latter would leak that you've been blocked."""
        from app.users.models import User

        with session_scope() as session:
            rows = (
                session.query(UserBlock, User)
                .join(User, User.id == UserBlock.blocked_id)
                .filter(UserBlock.blocker_id == user_id)
                .order_by(UserBlock.created_at.desc())
                .all()
            )
            return [
                {
                    "user_id": user.id,
                    "username": user.username,
                    "profile_picture": user.profile_picture,
                    "blocked_at": (
                        block.created_at.isoformat() if block.created_at else None
                    ),
                }
                for block, user in rows
            ]

    # ------------------------------------------------------------ moderation
    @staticmethod
    def resolve_report(
        report_id: str, reviewer_id: str, status: str, note: Optional[str] = None
    ) -> Dict[str, Any]:
        """Admin-only: close out a report."""
        try:
            new_status = ReportStatus(status)
        except ValueError:
            raise ValidationError("Unknown report status")

        with session_scope() as session:
            report = session.query(ContentReport).get(report_id)
            if not report:
                raise NotFoundError("Report not found")
            report.status = new_status
            report.reviewed_by = reviewer_id
            report.reviewed_at = datetime.utcnow()
            report.resolution_note = note or None
            return {
                "report_id": report.id,
                "status": report.status.value,
                "reviewed_at": report.reviewed_at.isoformat(),
            }
