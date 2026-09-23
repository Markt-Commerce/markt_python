"""Strip a photo of the things a seller did not mean to publish.

A phone photo carries EXIF, and EXIF routinely carries GPS: the exact spot the
picture was taken. A seller photographing stock at home and uploading it is
publishing their home address without knowing it, and Markt then serves that
file to anyone who opens the listing.

The variants generated for display are re-encoded through PIL and lose EXIF as
a side effect, but the *original* was uploaded exactly as received -- and the
original is what `Media.get_url()` hands out.

This is deliberate rather than incidental, and it happens before the bytes
reach storage, because a file that was written once has been kept.
"""

import logging
from io import BytesIO
from typing import Tuple

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Formats it is safe to re-encode without losing what makes them work. GIF is
# excluded on purpose: a naive re-save flattens an animation to one frame, and
# silently destroying someone's upload is worse than leaving its metadata on.
REENCODABLE = {"JPEG", "PNG", "WEBP"}

# EXIF tag 0x0112: which way up the camera was held.
ORIENTATION = 0x0112


def strip_metadata(data: bytes) -> Tuple[bytes, bool]:
    """Return (bytes, changed). Never raises.

    A photo that cannot be re-encoded is returned untouched: failing an upload
    over metadata would trade a privacy problem for a broken seller flow.
    """
    try:
        with Image.open(BytesIO(data)) as img:
            fmt = img.format
            if fmt not in REENCODABLE:
                return data, False

            # Orientation first. Cameras record "this is sideways" in EXIF
            # rather than rotating the pixels, so stripping EXIF without
            # applying it would leave every portrait photo on its side.
            #
            # Only when there is something to apply, though: transposing
            # returns a new image with no `format`, and a JPEG saved without
            # one cannot reuse the original's encoding settings. So a photo
            # that was never rotated is re-encoded with its own quantisation
            # tables -- visually identical to what the seller chose -- and
            # only a genuinely sideways one pays for a real re-encode.
            orientation = img.getexif().get(ORIENTATION, 1)
            rotated = orientation not in (None, 1)
            upright = ImageOps.exif_transpose(img) if rotated else img

            out = BytesIO()
            params = {}
            if fmt == "JPEG":
                if upright.mode not in ("RGB", "L", "CMYK"):
                    upright = upright.convert("RGB")
                    params = {"quality": 95}
                elif rotated:
                    params = {"quality": 95}
                else:
                    params = {"quality": "keep", "subsampling": "keep"}
            # PIL writes no EXIF, ICC profile or PNG text chunk unless it is
            # handed one, so simply saving is the strip.
            upright.save(out, format=fmt, **params)
            return out.getvalue(), True
    except Exception:
        logger.warning(
            "Could not strip metadata; storing the file as uploaded", exc_info=True
        )
        return data, False


def has_location(data: bytes) -> bool:
    """Whether a photo carries GPS EXIF. Used by tests and diagnostics."""
    try:
        with Image.open(BytesIO(data)) as img:
            exif = img.getexif()
            if not exif:
                return False
            # 0x8825 is the GPSInfo IFD pointer.
            return 0x8825 in exif
    except Exception:
        return False
