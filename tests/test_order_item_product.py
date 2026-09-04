"""Order rows need a product name and a thumbnail.

An order item carried only a product_id, so a client listing orders had to fetch
each product separately just to draw a row -- one request per line. The mobile
list didn't, and rendered "No image" on every order.
"""

from types import SimpleNamespace

from app.products.schemas import ProductSimpleSchema


def _product(images=None):
    return SimpleNamespace(id="PRD_1", name="Linen Shirt", images=images or [])


def test_product_summary_carries_id_name_and_image():
    media = SimpleNamespace(get_url=lambda: "https://cdn.test/shirt.jpg")
    product = _product([SimpleNamespace(media=media)])

    out = ProductSimpleSchema().dump(product)

    assert out["id"] == "PRD_1"
    assert out["name"] == "Linen Shirt"
    assert out["image_url"] == "https://cdn.test/shirt.jpg"


def test_product_with_no_images_reports_no_url_rather_than_failing():
    out = ProductSimpleSchema().dump(_product([]))
    assert out["image_url"] is None


def test_image_without_media_does_not_raise():
    """A ProductImage row whose media went missing must not take down the whole
    order list it appears in."""
    out = ProductSimpleSchema().dump(_product([SimpleNamespace(media=None)]))
    assert out["image_url"] is None


def test_a_broken_media_url_does_not_take_down_the_list():
    def boom():
        raise RuntimeError("signing failed")

    product = _product([SimpleNamespace(media=SimpleNamespace(get_url=boom))])
    out = ProductSimpleSchema().dump(product)
    assert out["image_url"] is None
