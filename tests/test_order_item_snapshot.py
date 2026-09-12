"""An order shows what was bought, not what the listing says today.

`price` has always been frozen at checkout. The name and the photo were not --
the order screens read them live off the product. So the classic swap was open:
sell the real thing, change the photo, ship the knockoff, and the buyer's own
receipt agrees with the seller. Sellers can now edit photos from the app, which
is what turned this from a curiosity into something worth closing.
"""

from types import SimpleNamespace

from app.orders.schemas import bought_product
from app.orders.snapshot import product_image_url, product_snapshot


def _product(name="Barcelona Jersey", url="https://cdn.example/real.jpg"):
    media = SimpleNamespace(get_url=lambda: url)
    return SimpleNamespace(id="PRD_A", name=name, images=[SimpleNamespace(media=media)])


def _item(product=None, **snapshot):
    return SimpleNamespace(
        product_id="PRD_A",
        product=product,
        product_name=snapshot.get("product_name"),
        product_image_url=snapshot.get("product_image_url"),
    )


# --- taking the snapshot ----------------------------------------------------


def test_a_snapshot_records_the_name_and_the_photo():
    assert product_snapshot(_product()) == (
        "Barcelona Jersey",
        "https://cdn.example/real.jpg",
    )


def test_a_product_with_no_photo_still_records_its_name():
    bare = SimpleNamespace(id="PRD_A", name="Barcelona Jersey", images=[])
    assert product_snapshot(bare) == ("Barcelona Jersey", None)


def test_an_unreadable_photo_never_fails_the_checkout():
    """A thumbnail is not worth failing a purchase over."""

    class Exploding:
        @property
        def images(self):
            raise RuntimeError("storage down")

    assert product_image_url(Exploding()) is None


def test_a_missing_product_snapshots_nothing_rather_than_raising():
    assert product_snapshot(None) == (None, None)


def test_an_overlong_url_is_dropped_rather_than_truncated():
    """The column is 500 wide. Half a signed URL renders a broken image, which
    is worse than falling back to the live one."""
    long_url = "https://cdn.example/" + "a" * 600
    name, url = product_snapshot(_product(url=long_url))
    assert name == "Barcelona Jersey"
    assert url is None


# --- reading it back --------------------------------------------------------


def test_the_receipt_shows_what_was_bought_not_what_is_listed_now():
    """The swap this exists to stop: the listing is now a different thing, and
    the order still says what was actually sold."""
    item = _item(
        product=_product(name="Cheap Knockoff", url="https://cdn.example/fake.jpg"),
        product_name="Barcelona Jersey",
        product_image_url="https://cdn.example/real.jpg",
    )
    got = bought_product(item)
    assert got["name"] == "Barcelona Jersey"
    assert got["image_url"] == "https://cdn.example/real.jpg"


def test_the_product_id_stays_live():
    """It is how the buyer opens the product again, and editing a listing does
    not change it."""
    item = _item(product=_product(), product_name="Barcelona Jersey")
    assert bought_product(item)["id"] == "PRD_A"


def test_an_order_placed_before_snapshots_existed_still_renders():
    got = bought_product(_item(product=_product()))
    assert got["name"] == "Barcelona Jersey"
    assert got["image_url"] == "https://cdn.example/real.jpg"


def test_each_field_falls_back_on_its_own():
    """A snapshot with a name but no photo takes the photo from the product
    rather than showing nothing."""
    item = _item(product=_product(name="Renamed"), product_name="Barcelona Jersey")
    got = bought_product(item)
    assert got["name"] == "Barcelona Jersey"
    assert got["image_url"] == "https://cdn.example/real.jpg"


def test_a_deleted_product_leaves_the_receipt_readable():
    """The product row is gone; the buyer still paid for something and is
    entitled to see what."""
    item = _item(
        product=None,
        product_name="Barcelona Jersey",
        product_image_url="https://cdn.example/real.jpg",
    )
    got = bought_product(item)
    assert got["name"] == "Barcelona Jersey"
    assert got["id"] == "PRD_A"
