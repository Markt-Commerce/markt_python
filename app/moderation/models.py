"""Trust & safety: content reports and user blocks.

App Store Review Guideline 1.2 requires apps with user-generated content to
ship a way to report objectionable content and a way to block abusive users,
alongside filtering and published contact details. Markt carries UGC in three
places -- posts, product listings and chat -- so reporting is deliberately
content-type agnostic rather than bolted onto posts alone.

Its own module rather than living under socials because it spans socials,
products and chats, and moderation state should not be owned by any one of
the things it moderates.
"""

from enum import Enum

from external.database import db
from app.libs.models import BaseModel
from app.libs.helpers import UniqueIdMixin


class ReportedContentType(Enum):
    POST = "post"
    PRODUCT = "product"
    COMMENT = "comment"
    CHAT_MESSAGE = "chat_message"
    USER = "user"


class ReportReason(Enum):
    SPAM = "spam"
    HARASSMENT = "harassment"
    HATE_SPEECH = "hate_speech"
    VIOLENCE = "violence"
    NUDITY = "nudity"
    SCAM_OR_FRAUD = "scam_or_fraud"
    COUNTERFEIT = "counterfeit"
    ILLEGAL_ITEM = "illegal_item"
    OTHER = "other"


class ReportStatus(Enum):
    PENDING = "pending"
    REVIEWING = "reviewing"
    ACTIONED = "actioned"
    DISMISSED = "dismissed"


class ContentReport(BaseModel, UniqueIdMixin):
    __tablename__ = "content_reports"
    id_prefix = "RPT_"

    id = db.Column(db.String(12), primary_key=True, default=None)
    reporter_id = db.Column(
        db.String(12), db.ForeignKey("users.id"), nullable=False, index=True
    )

    # Polymorphic by (type, id) rather than a nullable FK per content type:
    # five nullable columns with a check constraint is worse to read and worse
    # to extend, and moderation never needs to JOIN across all types at once.
    content_type = db.Column(db.Enum(ReportedContentType), nullable=False)
    content_id = db.Column(db.String(64), nullable=False)

    reason = db.Column(db.Enum(ReportReason), nullable=False)
    details = db.Column(db.Text, nullable=True)

    status = db.Column(
        db.Enum(ReportStatus), default=ReportStatus.PENDING, nullable=False, index=True
    )
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=True)
    resolution_note = db.Column(db.String(500), nullable=True)

    reporter = db.relationship("User", foreign_keys=[reporter_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

    __table_args__ = (
        # One report per user per item. A second tap should be a no-op, not a
        # way to inflate a queue -- and without this, a determined user could
        # spam the moderation backlog on their own.
        db.UniqueConstraint(
            "reporter_id",
            "content_type",
            "content_id",
            name="uq_report_reporter_content",
        ),
        db.Index("ix_content_reports_content", "content_type", "content_id"),
    )


class UserBlock(BaseModel):
    """A one-way block: blocker no longer sees blocked's content.

    Deliberately not symmetric. Blocking is about what *you* want to stop
    seeing; making it mutual would let anyone remove themselves from someone
    else's feed by blocking them first.
    """

    __tablename__ = "user_blocks"

    blocker_id = db.Column(db.String(12), db.ForeignKey("users.id"), primary_key=True)
    blocked_id = db.Column(
        db.String(12), db.ForeignKey("users.id"), primary_key=True, index=True
    )

    blocker = db.relationship("User", foreign_keys=[blocker_id])
    blocked = db.relationship("User", foreign_keys=[blocked_id])
