from .models import PostStatus


POST_STATUS_TRANSITIONS = {
    # action: (required_current_status, target_status)
    "publish": (PostStatus.DRAFT, PostStatus.ACTIVE),
    "archive": (PostStatus.ACTIVE, PostStatus.ARCHIVED),
    "unarchive": (PostStatus.ARCHIVED, PostStatus.ACTIVE),
    "delete": (None, PostStatus.DELETED),  # Can delete from any status
}
