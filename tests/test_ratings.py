"""Tests for rating correctness.

Each of these pins a defect that was live: ratings a seller never received,
reviews from people who never bought, and upvotes that could be spammed.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import APIError, ForbiddenError, NotFoundError
from app.products import ratings
from app.socials.services import ProductSocialService


class _Row(tuple):
    """Stands in for a SQLAlchemy result row."""


def _agg_session(rating_sum, rating_count, review_count=None, seller=None):
    session = MagicMock()
    row = (
        _Row((rating_sum, rating_count, review_count))
        if review_count is not None
        else _Row((rating_sum, rating_count))
    )
    session.query.return_value.filter.return_value.one.return_value = row
    session.query.return_value.join.return_value.filter.return_value.one.return_value = (
        row
    )
    session.query.return_value.get.return_value = seller
    return session


def test_product_rating_is_computed_from_the_database_not_a_cache():
    """Redis held rating_sum/rating_count and nothing ever reconciled them.

    Evict the key and every product silently dropped to 0 stars while the
    reviews sat untouched in Postgres.
    """
    session = _agg_session(rating_sum=22, rating_count=5, review_count=7)

    stats = ratings.product_rating_from_db(session, "PRD_1")

    assert stats["rating_sum"] == 22
    assert stats["rating_count"] == 5
    assert stats["review_count"] == 7
    assert stats["avg_rating"] == 4.4


def test_product_rating_of_a_product_with_no_ratings_is_zero_not_a_crash():
    session = _agg_session(rating_sum=0, rating_count=0, review_count=0)
    assert ratings.product_rating_from_db(session, "PRD_1")["avg_rating"] == 0.0


def test_refresh_seller_rating_writes_the_columns_nothing_used_to_write():
    """Seller.total_rating / total_raters were read in five places, exposed in
    the API, shown in the app and used as the shop directory's default sort --
    but no code path ever wrote them. Every seller read 0.00."""
    seller = SimpleNamespace(id=3, total_rating=0, total_raters=0)
    session = _agg_session(rating_sum=18, rating_count=4, seller=seller)

    result = ratings.refresh_seller_rating(session, 3)

    assert seller.total_rating == 18
    assert seller.total_raters == 4
    assert result["average_rating"] == 4.5


def test_refresh_seller_rating_is_safe_when_the_seller_is_gone():
    session = _agg_session(rating_sum=0, rating_count=0, seller=None)
    result = ratings.refresh_seller_rating(session, 999)
    assert result == {"total_rating": 0, "total_raters": 0, "average_rating": 0.0}


@patch("app.products.ratings.redis_client")
def test_a_failed_cache_write_does_not_fail_the_request(mock_redis):
    """The database already holds the truth; Redis is only a cache."""
    mock_redis.hset.side_effect = RuntimeError("redis down")
    session = _agg_session(rating_sum=10, rating_count=2, review_count=2)

    stats = ratings.refresh_product_rating(session, "PRD_1")

    assert stats["avg_rating"] == 5.0


@patch("app.socials.services.session_scope")
def test_review_requires_a_delivered_order(mock_scope):
    """Purchase verification used to run only `if data.get("order_id")`, so
    omitting the field skipped it and anyone could review anything."""
    session = MagicMock()
    session.query.return_value.get.return_value = SimpleNamespace(id="PRD_1")
    mock_scope.return_value.__enter__.return_value = session

    with patch.object(ProductSocialService, "_find_delivered_order", return_value=None):
        with pytest.raises(APIError) as exc:
            ProductSocialService.create_review("USR_1", "PRD_1", {"content": "hi"})

    assert exc.value.status_code == 403


@patch("app.socials.services.session_scope")
def test_review_rejects_an_unknown_product_before_anything_else(mock_scope):
    session = MagicMock()
    session.query.return_value.get.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(NotFoundError):
        ProductSocialService.create_review("USR_1", "PRD_MISSING", {"content": "hi"})


@patch("app.socials.services.refresh_for_product")
@patch("app.socials.services.session_scope")
def test_only_the_author_may_edit_a_review(mock_scope, _refresh):
    session = MagicMock()
    session.query.return_value.get.return_value = SimpleNamespace(
        id=1, user_id="USR_AUTHOR", product_id="PRD_1"
    )
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ForbiddenError):
        ProductSocialService.update_review("USR_SOMEONE_ELSE", 1, {"rating": 1})


@patch("app.socials.services.refresh_for_product")
@patch("app.socials.services.session_scope")
def test_only_the_author_may_delete_a_review(mock_scope, _refresh):
    session = MagicMock()
    session.query.return_value.get.return_value = SimpleNamespace(
        id=1, user_id="USR_AUTHOR", product_id="PRD_1"
    )
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ForbiddenError):
        ProductSocialService.delete_review("USR_SOMEONE_ELSE", 1)


@patch("app.socials.services.refresh_for_product")
@patch("app.socials.services.session_scope")
def test_deleting_a_review_refreshes_the_aggregates_it_fed(mock_scope, mock_refresh):
    """Otherwise the seller keeps stars from a review that no longer exists."""
    session = MagicMock()
    session.query.return_value.get.return_value = SimpleNamespace(
        id=1, user_id="USR_AUTHOR", product_id="PRD_1"
    )
    mock_scope.return_value.__enter__.return_value = session

    result = ProductSocialService.delete_review("USR_AUTHOR", 1)

    assert result == {"deleted": True, "review_id": 1}
    mock_refresh.assert_called_once()
    assert mock_refresh.call_args[0][1] == "PRD_1"
