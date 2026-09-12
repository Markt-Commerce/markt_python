"""Seller inventory search and filters, which have to run server-side.

The dashboard used to ask for 50 products and filter that list in the client.
That is fine only while the client pretends one page is the whole inventory:
the moment it pages properly, a search that looks at the current page finds
nothing and says so confidently.

Mocked session rather than a live database — what is worth pinning here is
that each argument reaches the query and that a bad one is refused, not that
Postgres can run an ILIKE.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import ValidationError
from app.products import services
from app.products.models import Product, ProductStatus
from app.products.services import LOW_STOCK_THRESHOLD, ProductService


def _scope(session):
    scope = MagicMock()
    scope.__enter__ = MagicMock(return_value=session)
    scope.__exit__ = MagicMock(return_value=False)
    return scope


def _session():
    """A session whose query chain records every filter applied to it."""
    session = MagicMock()
    chain = MagicMock()
    chain.filters = []

    def record(*args):
        chain.filters.extend(args)
        return chain

    chain.filter.side_effect = record
    chain.options.return_value = chain
    chain.order_by.return_value = chain
    chain.count.return_value = 0
    chain.offset.return_value.limit.return_value.all.return_value = []
    session.query.return_value = chain
    session.chain = chain
    return session


def _run(**kwargs):
    session = _session()
    with patch.object(services, "session_scope", return_value=_scope(session)):
        result = ProductService.get_seller_products(seller_id=1, **kwargs)
    return session.chain, result


def test_no_filters_applies_only_the_seller_scope():
    chain, _ = _run()
    # Just the seller_id filter the query is built with.
    assert len(chain.filters) == 1


def test_search_reaches_the_query():
    chain, _ = _run(search="ankara")
    rendered = " ".join(str(f) for f in chain.filters)
    assert "lower" in rendered.lower() or "ilike" in rendered.lower()


def test_search_matches_name_or_sku():
    """A seller hunting for their own product types one of those two."""
    chain, _ = _run(search="ABC-123")
    rendered = " ".join(str(f) for f in chain.filters).lower()
    assert "name" in rendered
    assert "sku" in rendered


def test_status_reaches_the_query():
    chain, _ = _run(status="active")
    assert any("status" in str(f).lower() for f in chain.filters)


def test_an_unknown_status_is_refused_rather_than_ignored():
    """Silently dropping it would return the whole catalogue as though
    nothing had been asked for, which reads as "the filter does nothing"."""
    with pytest.raises(ValidationError):
        _run(status="inactive")


def test_every_real_status_is_accepted():
    """`inactive` is not one of them — the mobile status menu offered it, and
    it could never have matched a product."""
    for status in ProductStatus:
        chain, _ = _run(status=status.value)
        assert any("status" in str(f).lower() for f in chain.filters)


def test_status_uses_the_enum_the_column_is_mapped_to():
    """There are two enums with identical members: a module-level
    `ProductStatus` and the nested `Product.Status` the column actually uses.

    Filtering with the wrong one binds as the string 'ProductStatus.DRAFT'
    and Postgres rejects it — a 500 that only appears against a real
    database, which is exactly how it got past the first run of these tests.
    """
    assert ProductStatus is not Product.Status
    chain, _ = _run(status="draft")
    bound = [
        f.right.value
        for f in chain.filters
        if hasattr(f, "right") and hasattr(f.right, "value")
    ]
    assert (
        Product.Status.DRAFT in bound
    ), "the filter must bind Product.Status, not the module-level enum"


def test_the_pagination_carries_a_usable_count():
    """PaginationSchema declares `total_items`; the service used to emit only
    `total`, so serialisation dropped it and the client could count pages but
    never results."""
    _, result = _run()
    assert "total_items" in result["pagination"]


def test_low_stock_filters_on_the_threshold():
    chain, _ = _run(low_stock=True)
    rendered = " ".join(str(f) for f in chain.filters).lower()
    assert "stock" in rendered


def test_low_stock_is_off_unless_asked_for():
    chain, _ = _run()
    assert not any("stock <" in str(f).lower() for f in chain.filters)


def test_the_threshold_matches_the_dashboard():
    """The client shows a low-stock alert at the same number; two thresholds
    that disagree is a row that is red in one place and not the other."""
    assert LOW_STOCK_THRESHOLD == 5


def test_filters_combine():
    chain, _ = _run(search="pear", status="active", low_stock=True)
    rendered = " ".join(str(f) for f in chain.filters).lower()
    assert "name" in rendered and "status" in rendered and "stock" in rendered
