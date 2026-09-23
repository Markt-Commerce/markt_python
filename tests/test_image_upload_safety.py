"""What happens to a photo between the seller picking it and Markt serving it.

Two things did not happen before: nothing looked at the image, and the
original was stored byte-for-byte as uploaded -- EXIF, GPS and all. The
display variants are re-encoded and lose EXIF as a side effect, but the
original is what Media.get_url() hands out.
"""

from fractions import Fraction
from io import BytesIO
from unittest.mock import patch

from PIL import Image

from app.media.moderation import Verdict, scan_image
from app.media.sanitize import has_location, strip_metadata


ORIENTATION = 0x0112
GPS_IFD = 0x8825


def _jpeg(size=(48, 32), gps=True, orientation=None) -> bytes:
    """A small JPEG, optionally carrying the coordinates it was 'taken' at.

    Written with Pillow rather than a dedicated EXIF library so the tests add
    no dependency the app does not already have.
    """
    img = Image.new("RGB", size, (120, 80, 40))
    exif = Image.Exif()
    if orientation is not None:
        exif[ORIENTATION] = orientation
    if gps:
        # Somewhere in Ibadan, which is the point: this is a home address.
        exif[GPS_IFD] = {
            1: "N",
            2: (Fraction(7), Fraction(26), Fraction(0)),
            3: "E",
            4: (Fraction(3), Fraction(54), Fraction(0)),
        }
    out = BytesIO()
    img.save(out, format="JPEG", quality=90, exif=exif.tobytes())
    return out.getvalue()


def _jpeg_with_gps() -> bytes:
    return _jpeg()


# --- metadata ---------------------------------------------------------------


def test_a_photo_arrives_carrying_where_it_was_taken():
    """The premise. If this fails the rest proves nothing."""
    assert has_location(_jpeg_with_gps())


def test_the_location_does_not_survive_the_upload():
    cleaned, changed = strip_metadata(_jpeg_with_gps())
    assert changed
    assert not has_location(cleaned)


def test_the_photo_still_works_afterwards():
    cleaned, _ = strip_metadata(_jpeg_with_gps())
    with Image.open(BytesIO(cleaned)) as img:
        assert img.size == (48, 32)
        assert img.format == "JPEG"


def test_a_sideways_photo_is_not_left_sideways():
    """Cameras record "this is rotated" in EXIF rather than rotating pixels.
    Stripping EXIF without applying it first would tip every portrait photo
    onto its side."""
    # 6 = rotate 90 degrees clockwise on display.
    sideways = _jpeg(size=(40, 20), gps=False, orientation=6)
    cleaned, changed = strip_metadata(sideways)
    assert changed
    with Image.open(BytesIO(cleaned)) as out:
        # The rotation is baked into the pixels now, so width and height swap.
        assert out.size == (20, 40)


def test_an_animated_gif_is_left_alone():
    """Re-saving one naively flattens it to a single frame. Destroying an
    upload is worse than leaving its metadata on."""
    frames = [Image.new("P", (8, 8), i) for i in (1, 2, 3)]
    raw = BytesIO()
    frames[0].save(raw, format="GIF", save_all=True, append_images=frames[1:])
    original = raw.getvalue()

    cleaned, changed = strip_metadata(original)
    assert not changed
    assert cleaned == original


def test_something_that_is_not_an_image_is_returned_untouched():
    """Validation refuses it moments later; this must not be what raises."""
    junk = b"not an image at all"
    assert strip_metadata(junk) == (junk, False)


def test_a_png_keeps_its_transparency():
    img = Image.new("RGBA", (16, 16), (255, 0, 0, 0))
    raw = BytesIO()
    img.save(raw, format="PNG")
    cleaned, changed = strip_metadata(raw.getvalue())
    assert changed
    with Image.open(BytesIO(cleaned)) as out:
        assert out.mode == "RGBA"
        assert out.getpixel((0, 0))[3] == 0


# --- moderation -------------------------------------------------------------


def test_with_no_provider_nothing_is_blocked_and_nothing_claims_to_be_scanned():
    """ "Nobody looked" and "someone looked and it was fine" are different
    facts. Collapsing them is how an unscanned image gets called clean."""
    verdict = scan_image(b"bytes", "photo.jpg", "USR_1")
    assert verdict.allowed
    assert verdict.scanned is False


def test_a_provider_that_refuses_an_image_is_honoured():
    with patch(
        "app.media.moderation._provider",
        return_value=lambda *a: Verdict(False, True, "prohibited content"),
    ):
        verdict = scan_image(b"bytes", "photo.jpg", "USR_1")
    assert not verdict.allowed
    assert verdict.reason == "prohibited content"


def test_a_scanner_that_is_down_does_not_stop_people_selling():
    """Failing open is a decision: the reactive path still exists, and
    blocking every upload because a third party is unreachable is the larger
    harm. It is recorded as unscanned, not as passed."""

    def explode(*_args):
        raise RuntimeError("vision api down")

    with patch("app.media.moderation._provider", return_value=explode):
        verdict = scan_image(b"bytes", "photo.jpg", "USR_1")
    assert verdict.allowed
    assert verdict.scanned is False


def test_a_configured_but_unimplemented_provider_does_not_pretend_to_scan():
    """Setting the env var must not quietly buy false confidence."""
    from main.config import settings

    with patch.object(settings, "IMAGE_MODERATION_PROVIDER", "google_safesearch"):
        verdict = scan_image(b"bytes", "photo.jpg", "USR_1")
    assert verdict.allowed
    assert verdict.scanned is False
