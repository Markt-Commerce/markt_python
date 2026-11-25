"""/location/nearby only returns products that are on sale.

Both the radius search and the nationwide fallback used to return drafts,
archived and soft-deleted products.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.location import services
from app.products.models import Product
from app.users.models import Seller


def _sql_of_filters(session):
    """Every SQL fragment passed to .filter() anywhere on the query chain."""
    fragments = []
    for call in session.mock_calls:
        if call[0].endswith("filter"):
            fragments.extend(str(arg) for arg in call.args)
    return " ".join(fragments)


def _run(fn):
    session = MagicMock()

    @contextmanager
    def scope():
        yield session

    with patch.object(services, "read_scope", scope):
        fn()
    return _sql_of_filters(session)


def test_radius_search_filters_on_status():
    sql = _run(
        lambda: services._within_radius(Product, Seller, 7.44, 3.9, 10, 20, None)
    )
    assert "products.status" in sql


def test_nationwide_fallback_filters_on_status():
    sql = _run(lambda: services._nationwide(20, None, reason="test"))
    assert "products.status" in sql
