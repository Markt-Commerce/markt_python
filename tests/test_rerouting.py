"""Unit tests for the rerouting engine's candidate-seller lookup and hard
eligibility filter (§7.1-7.2)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.fulfilment.rerouting import (
    PRICE_HEADROOM_RATE,
    _tokenize,
    filter_eligible_candidates,
    find_candidate_products,
)
from app.inventory.confidence import ConfidenceBand


def test_tokenize_strips_stopwords_short_tokens_and_punctuation():
    assert _tokenize("Rice, 5kg (Local)") == ["rice", "5kg", "local"]
    assert _tokenize("A Bag of Rice") == ["bag", "rice"]


def test_tokenize_empty_for_blank_name():
    assert _tokenize("") == []
    assert _tokenize(None) == []


def test_find_candidate_products_empty_when_no_keywords():
    session = MagicMock()
    product = SimpleNamespace(id="PRD_1", name="")

    result = find_candidate_products(session, product, exclude_seller_id=7)

    assert result == []
    session.query.assert_not_called()


def test_find_candidate_products_empty_when_no_primary_category():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    product = SimpleNamespace(id="PRD_1", name="Rice 5kg")

    result = find_candidate_products(session, product, exclude_seller_id=7)

    assert result == []


def test_find_candidate_products_empty_when_seller_has_no_market():
    session = MagicMock()
    category = SimpleNamespace(category_id=3)
    seller_no_market = SimpleNamespace(market_id=None)

    def query_side_effect(model):
        mock = MagicMock()
        name = getattr(model, "__name__", None)
        if name == "ProductCategory":
            mock.filter_by.return_value.first.return_value = category
        elif name == "Seller":
            mock.get.return_value = seller_no_market
        return mock

    session.query.side_effect = query_side_effect
    product = SimpleNamespace(id="PRD_1", name="Rice 5kg")

    result = find_candidate_products(session, product, exclude_seller_id=7)

    assert result == []


def test_find_candidate_products_returns_query_results_when_scoped():
    session = MagicMock()
    category = SimpleNamespace(category_id=3)
    seller = SimpleNamespace(market_id=5)
    expected = [SimpleNamespace(id="PRD_2")]

    def query_side_effect(model):
        mock = MagicMock()
        name = getattr(model, "__name__", None)
        if name == "ProductCategory":
            mock.filter_by.return_value.first.return_value = category
        elif name == "Seller":
            mock.get.return_value = seller
        elif name == "Product":
            # Chain every builder method back to the same mock so the
            # exact number of .filter() calls in the loop doesn't matter.
            mock.join.return_value = mock
            mock.filter.return_value = mock
            mock.all.return_value = expected
        return mock

    session.query.side_effect = query_side_effect
    product = SimpleNamespace(id="PRD_1", name="Rice 5kg")

    result = find_candidate_products(session, product, exclude_seller_id=7)

    assert result == expected


@patch("app.fulfilment.rerouting.find_candidate_products")
@patch("app.fulfilment.rerouting.InventoryConfidenceService.get_band_for_product")
def test_filter_eligible_candidates_excludes_over_price_ceiling(mock_band, mock_find):
    session = MagicMock()
    within = SimpleNamespace(id="PRD_2", price=1040.0, variants=[])
    over = SimpleNamespace(id="PRD_3", price=1060.0, variants=[])
    mock_find.return_value = [within, over]
    mock_band.return_value = ConfidenceBand.HIGH

    original = SimpleNamespace(id="PRD_1", name="Rice 5kg")
    result = filter_eligible_candidates(session, original, 1000.0, exclude_seller_id=7)

    assert result == [within]
    assert within.price <= 1000.0 * (1 + PRICE_HEADROOM_RATE)


@patch("app.fulfilment.rerouting.find_candidate_products")
@patch("app.fulfilment.rerouting.InventoryConfidenceService.get_band_for_product")
def test_filter_eligible_candidates_excludes_low_confidence(mock_band, mock_find):
    session = MagicMock()
    candidate = SimpleNamespace(id="PRD_2", price=1000.0, variants=[])
    mock_find.return_value = [candidate]
    mock_band.return_value = ConfidenceBand.LOW

    original = SimpleNamespace(id="PRD_1", name="Rice 5kg")
    result = filter_eligible_candidates(session, original, 1000.0, exclude_seller_id=7)

    assert result == []


@patch("app.fulfilment.rerouting.find_candidate_products")
@patch("app.fulfilment.rerouting.InventoryConfidenceService.get_band_for_product")
def test_filter_eligible_candidates_medium_confidence_is_eligible(mock_band, mock_find):
    session = MagicMock()
    candidate = SimpleNamespace(id="PRD_2", price=1000.0, variants=[])
    mock_find.return_value = [candidate]
    mock_band.return_value = ConfidenceBand.MEDIUM

    original = SimpleNamespace(id="PRD_1", name="Rice 5kg")
    result = filter_eligible_candidates(session, original, 1000.0, exclude_seller_id=7)

    assert result == [candidate]


@patch("app.fulfilment.rerouting.find_candidate_products")
def test_filter_eligible_candidates_excludes_variant_incompatible(mock_find):
    session = MagicMock()
    no_variants = SimpleNamespace(id="PRD_2", price=1000.0, variants=[])
    mock_find.return_value = [no_variants]

    original = SimpleNamespace(id="PRD_1", name="Rice 5kg")
    result = filter_eligible_candidates(
        session, original, 1000.0, exclude_seller_id=7, variant_id=9
    )

    assert result == []
