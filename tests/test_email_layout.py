"""The seller analytics report, and the email-safe primitives under it.

These assertions are about what a subscriber sees, so they are written against
the rendered string rather than the helpers' internals. The two that matter
most are the negative ones: no CSS grid or flexbox anywhere (Gmail and Outlook
drop both, which is what made the old report collapse into a column of
unlabelled numbers), and no comparison line when there is nothing to compare
against.
"""

import re

from app.libs import email_layout as L
from app.libs.email_service import EmailService


def render(**overrides):
    data = {
        "period": "September 2026",
        "shop_name": "Ameth Stores",
        "total_sales": 486500.0,
        "total_orders": 55,
        "total_products": 12,
        "previous": {"total_sales": 402000.0, "total_orders": 49},
        "top_products": [
            {"name": "Barcelona Jersey", "sales": 18, "revenue": 270000.0},
        ],
    }
    data.update(overrides)
    svc = EmailService.__new__(EmailService)
    return svc._get_seller_analytics_report_template(data)


def text_of(html):
    """What the email reads as once the markup is gone."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class TestEmailSafety:
    def test_no_grid_or_flex_layout(self):
        html = render()
        assert "display:grid" not in html.replace(" ", "")
        assert "display:flex" not in html.replace(" ", "")

    def test_layout_is_tables(self):
        assert render().count("<table") >= 4

    def test_has_a_preheader(self):
        # The line an inbox shows after the subject. Without it the client
        # picks the first text in the body, which is rarely the point.
        html = render()
        assert "display:none" in html.replace(" ", "")
        assert "55 orders" in html

    def test_fixed_width_for_desktop_clients(self):
        assert f'width="{L.WIDTH}"' in render()


class TestReportContent:
    def test_names_the_shop_and_period(self):
        body = text_of(render())
        assert "Ameth Stores" in body
        assert "September 2026" in body

    def test_money_is_formatted_with_currency(self):
        assert "₦486,500.00" in text_of(render())

    def test_comparison_carries_the_currency_symbol(self):
        # A bare "84,500 more" reads as a count of something, not naira.
        assert "₦84,500 more than the month before" in text_of(render())

    def test_no_comparison_when_there_is_no_previous_period(self):
        body = text_of(render(previous=None))
        assert "than the month" not in body
        assert "₦486,500.00" in body

    def test_quarterly_period_says_quarter(self):
        body = text_of(render(period="Q3 2026"))
        assert "quarter" in body

    def test_top_products_table_lists_what_sold(self):
        body = text_of(render())
        assert "Barcelona Jersey" in body
        assert "18" in body

    def test_no_empty_table_when_nothing_sold_yet(self):
        # An empty table with only headings looks like a rendering failure.
        html = render(top_products=[])
        assert "What sold most" not in text_of(html)


class TestZeroOrderMonth:
    def test_does_not_report_a_drop_to_a_seller_with_no_sales(self):
        body = text_of(render(total_sales=0, total_orders=0, previous=None))
        assert "than the month before" not in body

    def test_says_something_useful_instead_of_zeroes(self):
        body = text_of(render(total_sales=0, total_orders=0, previous=None))
        assert "No sales" in body

    def test_no_division_by_zero_for_average_order(self):
        # total_sales / total_orders with no orders used to raise.
        render(total_sales=0, total_orders=0, previous=None)


class TestChangeLine:
    def test_blank_without_a_previous_value(self):
        assert L.change_line(100.0, None, "month") == ""

    def test_says_so_when_unchanged(self):
        assert L.change_line(100.0, 100.0, "month") == "Same as the month before."

    def test_reports_a_rise(self):
        assert "more than the month before" in L.change_line(150.0, 100.0, "month")

    def test_reports_a_fall(self):
        line = L.change_line(50.0, 100.0, "month")
        assert "less than the month before" in line
        # The drop is stated as a positive amount, not "-50".
        assert "-" not in line

    def test_prefix_is_applied(self):
        assert L.change_line(150.0, 100.0, "month", prefix="₦").startswith("₦")


class TestTableBlock:
    def test_empty_rows_render_nothing_at_all(self):
        assert L.table_block(["Product"], [], title="What sold most") == ""

    def test_headings_and_rows_both_appear(self):
        html = L.table_block(["Product", "Sold"], [["Tote", "9"]])
        assert "Product" in html and "Tote" in html


class TestButton:
    def test_is_a_table_so_outlook_renders_it(self):
        html = L.button("Open your dashboard", "https://example.test/d")
        assert "<table" in html
        assert 'href="https://example.test/d"' in html


class TestEscaping:
    """Everything these helpers interpolate is somebody's typed-in text."""

    NASTY = '<script>alert("x")</script> & "Ade\'s" <b>Shop</b>'

    def test_a_product_name_cannot_inject_markup(self):
        html = render(top_products=[{"name": self.NASTY, "sales": 1, "revenue": 10.0}])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_a_shop_name_cannot_inject_markup(self):
        html = render(shop_name=self.NASTY)
        assert "<script>" not in html

    def test_a_url_cannot_break_out_of_its_attribute(self):
        html = L.button("Go", 'https://x.test/"onmouseover="alert(1)')
        assert '"onmouseover=' not in html
        assert "&quot;onmouseover=" in html

    def test_table_cells_and_headings_are_escaped(self):
        html = L.table_block([self.NASTY], [[self.NASTY]])
        assert "<script>" not in html

    def test_progress_step_labels_are_escaped(self):
        assert "<script>" not in L.progress([self.NASTY, "B"], 0)

    def test_detail_values_are_escaped(self):
        assert "<script>" not in L.detail_rows([["Order", self.NASTY]])

    def test_the_built_body_is_not_double_escaped(self):
        # shell()'s body is already markup; escaping it would print the tags.
        html = L.shell("T", "P", L.note("hello"), "footer")
        assert "&lt;tr&gt;" not in html
        assert "<tr>" in html

    def test_none_does_not_become_the_word_none(self):
        assert L.esc(None) == ""
