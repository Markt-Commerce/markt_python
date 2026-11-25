"""Business logo and cover image.

Uploaded through Markt's own media pipeline (like a shop banner,
UserService.upload_shop_banner) rather than accepted as a URL, so a profile
can only ever show an image its owner uploaded — never an arbitrary
off-site address. Replacing an image deletes the old one.
"""

import logging
from io import BytesIO
from urllib.parse import urlparse

from app.libs.errors import NotFoundError
from app.libs.session import session_scope

from .models import BusinessProfile

logger = logging.getLogger(__name__)

# kind -> (BusinessProfile column, alt text)
KINDS = {
    "logo": ("logo_url", "Business logo"),
    "cover": ("cover_image_url", "Business cover image"),
}


def _delete_by_url(session, url: str) -> None:
    from app.media.models import Media, MediaVariant
    from app.media.services import media_service

    storage_key = urlparse(url).path.lstrip("/")
    old = session.query(Media).filter_by(storage_key=storage_key).first()
    if not old:
        return
    try:
        media_service.delete_media(old)
    except Exception as e:  # noqa: BLE001
        # A stale object in storage isn't worth failing the user's upload.
        logger.warning("Could not delete old business image: %s", e)
    session.query(MediaVariant).filter_by(media_id=old.id).delete()
    session.delete(old)


def upload_business_image(user_id: str, kind: str, file_stream, filename: str):
    """Upload and set the logo or cover. Returns the Media row."""
    from app.media.services import media_service

    column, alt_text = KINDS[kind]
    if not isinstance(file_stream, BytesIO):
        file_stream = BytesIO(file_stream.read())

    with session_scope() as session:
        profile = session.query(BusinessProfile).filter_by(user_id=user_id).first()
        if not profile:
            raise NotFoundError("Set up your business profile first")
        old_url = getattr(profile, column)
        if old_url:
            _delete_by_url(session, old_url)
            setattr(profile, column, None)

    media = media_service.upload_image(
        file_stream=file_stream,
        filename=filename,
        user_id=user_id,
        alt_text=alt_text,
        caption=alt_text,
    )

    with session_scope() as session:
        profile = session.query(BusinessProfile).filter_by(user_id=user_id).first()
        setattr(profile, column, media.get_url())
    return media


def remove_business_image(user_id: str, kind: str) -> None:
    column, _ = KINDS[kind]
    with session_scope() as session:
        profile = session.query(BusinessProfile).filter_by(user_id=user_id).first()
        if not profile:
            raise NotFoundError("Set up your business profile first")
        old_url = getattr(profile, column)
        if old_url:
            _delete_by_url(session, old_url)
            setattr(profile, column, None)
