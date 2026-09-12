"""Whether an uploaded image is allowed to exist.

Markt's moderation today is entirely reactive: someone sees something, reports
it (app.moderation.ContentReport), and a human acts. Nothing looks at an image
as it arrives, so a prohibited photo is public until a person happens to
notice.

This is the seam for the proactive half. It is deliberately a seam and not an
implementation: every credible scanner (Cloud Vision SafeSearch, AWS
Rekognition) is a paid third-party call needing credentials Markt does not
have yet, and inventing a local heuristic here would be worse than nothing --
it would look like a control while catching nothing.

So: one place the upload path already calls, a provider chosen by config, and
a default that says plainly that no scanning happened rather than pretending
an image was checked and passed.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Verdict:
    """`allowed` is the only thing callers must honour.

    `scanned` is separate on purpose: "nobody looked" and "someone looked and
    it was fine" are different facts, and collapsing them is how an unscanned
    image comes to be described as clean.
    """

    allowed: bool
    scanned: bool
    reason: Optional[str] = None


ALLOWED_UNSCANNED = Verdict(allowed=True, scanned=False, reason="no scanner configured")


def scan_image(data: bytes, filename: str, user_id: Optional[str] = None) -> Verdict:
    """Check an image before it is stored.

    Returns a Verdict; the caller refuses the upload when `allowed` is False.
    With no provider configured this allows everything and says so, which is
    exactly today's behaviour -- made visible instead of implicit.
    """
    provider = _provider()
    if not provider:
        return ALLOWED_UNSCANNED

    try:
        return provider(data, filename, user_id)
    except Exception:
        # A scanner that is down must not stop people selling. Failing open is
        # a decision, not an accident: the reactive path (reports) still
        # exists, and blocking every upload because a third party is
        # unreachable is the larger harm.
        logger.exception("Image moderation provider failed; allowing the upload")
        return Verdict(allowed=True, scanned=False, reason="scanner unavailable")


def _provider():
    """The configured scanner, or None.

    Resolved per call rather than at import so the setting can be switched
    without a restart, and so tests can patch it.
    """
    try:
        from main.config import settings

        name = (getattr(settings, "IMAGE_MODERATION_PROVIDER", "") or "").strip()
    except Exception:
        return None

    if not name or name.lower() in ("none", "off", "disabled"):
        return None

    logger.error(
        "IMAGE_MODERATION_PROVIDER is set to %r but no provider is implemented; "
        "uploads are NOT being scanned",
        name,
    )
    return None
