"""The order email's progress bar, and what it says was bought.

The bar rendered as one dot on the left and three bunched at the right,
under four evenly-spread labels. It was built as two separate tables --
one of dots and connectors, one of labels -- with different numbers of
cells in each, so nothing made the rows line up; and every connector
asked for width="100%", so a client handed the first one the whole row
and collapsed the rest.

Separately, a delivery email said "Your order arrived" and named no
part of the order, so a buyer with two open had to go and look.
"""

import re

from app.libs import email_layout as L
from app.libs.email_service import EmailService

STEPS = ["Confirmed", "Packed", "On the way", "Delivered"]


def cell_widths(html: str):
    return re.findall(r'<td width="([\d.]+)%"', html)


class TestEveryStepGetsTheSameWidth:
    def test_four_steps_are_four_equal_cells(self):
        widths = cell_widths(L.progress(STEPS, 3))
        assert widths == ["25.0"] * 4

    def test_three_steps_divide_evenly_too(self):
        widths = cell_widths(L.progress(["A", "B", "C"], 0))
        assert len(widths) == 3
        assert len(set(widths)) == 1

    def test_no_sibling_cell_claims_the_whole_row(self):
        # The actual defect. Several connector <td>s each asked for
        # 100%, so a client gave the first one everything and collapsed
        # the rest. A nested *table* at 100% is fine -- that is just a
        # table filling the cell it is in -- so this looks only at
        # cells.
        assert '<td width="100%"' not in L.progress(STEPS, 2)

    def test_the_dot_and_its_label_share_one_cell(self):
        # Which is the only thing that keeps them lined up. Two tables
        # with different cell counts cannot be made to agree.
        html = L.progress(STEPS, 1)
        for step in STEPS:
            cell = html.split(f">{step}</div>")[0]
            opened = cell.rfind('<td width="25.0%"')
            # The dot for this step is inside the same cell as its word,
            # with no cell boundary between them.
            assert opened != -1
            assert "border-radius:7px" in cell[opened:]


class TestTheBarStillMeansSomething:
    def test_completed_steps_are_branded(self):
        # Every step done: no hairline left anywhere but the blank
        # outer connectors, which are transparent.
        html = L.progress(STEPS, len(STEPS) - 1)
        assert L.HAIRLINE not in html

    def test_an_early_step_leaves_the_rest_grey(self):
        html = L.progress(STEPS, 0)
        assert L.HAIRLINE in html and L.BRAND in html

    def test_the_line_does_not_run_off_either_end(self):
        html = L.progress(STEPS, 3)
        assert html.count("transparent") == 2

    def test_an_unknown_step_is_clamped_not_raised(self):
        assert L.progress(STEPS, 99)
        assert L.progress(STEPS, -5)

    def test_no_steps_renders_nothing(self):
        assert L.progress([], 0) == ""


class TestTheEmailSaysWhatWasBought:
    def _items(self):
        return [
            {
                "product_name": "Fresh Bush Pear",
                "quantity": 2,
                "price": 1500,
                "image_url": "https://cdn/pear.jpg",
            },
            {"product_name": "iPad Air", "quantity": 1, "price": 650000},
        ]

    def test_the_status_email_lists_them(self):
        html = EmailService.__new__(EmailService)._get_order_status_update_template(
            {"order_number": "ORD-1", "status": "delivered", "items": self._items()}
        )
        assert "Fresh Bush Pear" in html
        assert "iPad Air" in html

    def test_a_product_with_a_photo_shows_it(self):
        html = L.line_items(self._items())
        assert 'src="https://cdn/pear.jpg"' in html
        # Sized in the attribute too, because Outlook ignores the CSS.
        assert 'width="56" height="56"' in html

    def test_a_product_without_one_keeps_its_row(self):
        # A missing photo is not a missing purchase.
        html = L.line_items([{"product_name": "iPad Air", "quantity": 1}])
        assert "iPad Air" in html
        assert "<img" not in html

    def test_an_order_with_no_items_renders_nothing(self):
        assert L.line_items([]) == ""

    def test_a_name_cannot_break_the_markup(self):
        html = L.line_items([{"product_name": "<script>x</script>", "quantity": 1}])
        assert "<script>" not in html


class TestThumbnailLookup:
    def test_the_featured_image_wins(self):
        from types import SimpleNamespace

        from app.notifications.tasks import _product_thumbnail

        plain = SimpleNamespace(
            is_featured=False, media=SimpleNamespace(get_url=lambda: "plain.jpg")
        )
        featured = SimpleNamespace(
            is_featured=True, media=SimpleNamespace(get_url=lambda: "featured.jpg")
        )
        product = SimpleNamespace(images=[plain, featured])
        assert _product_thumbnail(product) == "featured.jpg"

    def test_otherwise_the_first_by_sort_order(self):
        from types import SimpleNamespace

        from app.notifications.tasks import _product_thumbnail

        product = SimpleNamespace(
            images=[
                SimpleNamespace(
                    is_featured=False, media=SimpleNamespace(get_url=lambda: "one.jpg")
                ),
                SimpleNamespace(
                    is_featured=False, media=SimpleNamespace(get_url=lambda: "two.jpg")
                ),
            ]
        )
        assert _product_thumbnail(product) == "one.jpg"

    def test_a_product_with_no_images_is_empty_not_an_error(self):
        from types import SimpleNamespace

        from app.notifications.tasks import _product_thumbnail

        assert _product_thumbnail(SimpleNamespace(images=[])) == ""
        assert _product_thumbnail(None) == ""

    def test_a_storage_backend_that_throws_does_not_stop_the_email(self):
        from types import SimpleNamespace

        from app.notifications.tasks import _product_thumbnail

        def boom():
            raise RuntimeError("no bucket")

        product = SimpleNamespace(
            images=[
                SimpleNamespace(is_featured=True, media=SimpleNamespace(get_url=boom))
            ]
        )
        assert _product_thumbnail(product) == ""
