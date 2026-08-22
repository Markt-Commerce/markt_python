"""Unit tests for the seller ranking scorer (13.1) and quantity-split
penalty (13.3)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.fulfilment.ranking import (
    DEFAULT_DISTANCE_DELIVERY_COST_SCORE,
    QUANTITY_SPLIT_PENALTY,
    WEIGHTS,
    _price_compatibility,
    rank_candidates,
    score_candidate,
)


def test_price_compatibility_full_score_at_or_below_original():
    assert _price_compatibility(900.0, 1000.0) == 1.0
    assert _price_compatibility(1000.0, 1000.0) == 1.0


def test_price_compatibility_zero_at_ceiling():
    ceiling = 1000.0 * 1.05
    assert _price_compatibility(ceiling, 1000.0) == 0.0
    assert _price_compatibility(ceiling + 10, 1000.0) == 0.0


def test_price_compatibility_midway_between_original_and_ceiling():
    ceiling = 1000.0 * 1.05  # 1050
    midpoint = 1025.0
    assert _price_compatibility(midpoint, 1000.0) == pytest.approx(0.5)


def test_price_compatibility_zero_for_non_positive_original():
    assert _price_compatibility(500.0, 0.0) == 0.0


@patch("app.fulfilment.ranking.SellerReliabilityService.get_response_rate")
@patch("app.fulfilment.ranking.SellerReliabilityService.get_score")
@patch("app.fulfilment.ranking.InventoryConfidenceService.get_score_for_product")
def test_score_candidate_combines_weighted_components(
    mock_confidence, mock_reliability, mock_response_rate
):
    mock_confidence.return_value = 1.0
    mock_reliability.return_value = 1.0
    mock_response_rate.return_value = 1.0
    product = SimpleNamespace(id="PRD_2", seller_id=8, price=1000.0)

    result = score_candidate(product, original_price=1000.0)

    expected = round(
        WEIGHTS["inventory_confidence"] * 1.0
        + WEIGHTS["seller_reliability"] * 1.0
        + WEIGHTS["distance_delivery_cost"] * DEFAULT_DISTANCE_DELIVERY_COST_SCORE
        + WEIGHTS["price_compatibility"] * 1.0
        + WEIGHTS["response_reliability"] * 1.0,
        4,
    )
    assert result["score"] == expected
    assert result["would_split"] is False


@patch("app.fulfilment.ranking.InventoryService.get_available_quantity")
@patch("app.fulfilment.ranking.SellerReliabilityService.get_response_rate")
@patch("app.fulfilment.ranking.SellerReliabilityService.get_score")
@patch("app.fulfilment.ranking.InventoryConfidenceService.get_score_for_product")
def test_score_candidate_applies_quantity_split_penalty(
    mock_confidence, mock_reliability, mock_response_rate, mock_available
):
    mock_confidence.return_value = 1.0
    mock_reliability.return_value = 1.0
    mock_response_rate.return_value = 1.0
    mock_available.return_value = 2  # less than needed_quantity=5
    product = SimpleNamespace(id="PRD_2", seller_id=8, price=1000.0)

    result = score_candidate(product, original_price=1000.0, needed_quantity=5)

    base_score = round(
        WEIGHTS["inventory_confidence"] * 1.0
        + WEIGHTS["seller_reliability"] * 1.0
        + WEIGHTS["distance_delivery_cost"] * DEFAULT_DISTANCE_DELIVERY_COST_SCORE
        + WEIGHTS["price_compatibility"] * 1.0
        + WEIGHTS["response_reliability"] * 1.0,
        4,
    )
    assert result["would_split"] is True
    assert result["score"] == pytest.approx(
        round(base_score * (1 - QUANTITY_SPLIT_PENALTY), 4)
    )


@patch("app.fulfilment.ranking.InventoryService.get_available_quantity")
@patch("app.fulfilment.ranking.SellerReliabilityService.get_response_rate")
@patch("app.fulfilment.ranking.SellerReliabilityService.get_score")
@patch("app.fulfilment.ranking.InventoryConfidenceService.get_score_for_product")
def test_score_candidate_no_penalty_when_quantity_fully_covered(
    mock_confidence, mock_reliability, mock_response_rate, mock_available
):
    mock_confidence.return_value = 1.0
    mock_reliability.return_value = 1.0
    mock_response_rate.return_value = 1.0
    mock_available.return_value = 10
    product = SimpleNamespace(id="PRD_2", seller_id=8, price=1000.0)

    result = score_candidate(product, original_price=1000.0, needed_quantity=5)

    assert result["would_split"] is False


@patch("app.fulfilment.ranking.SellerReliabilityService.get_response_rate")
@patch("app.fulfilment.ranking.SellerReliabilityService.get_score")
@patch("app.fulfilment.ranking.InventoryConfidenceService.get_score_for_product")
def test_rank_candidates_orders_highest_score_first(
    mock_confidence, mock_reliability, mock_response_rate
):
    mock_reliability.return_value = 0.5
    mock_response_rate.return_value = 0.5
    # Higher confidence -> higher overall score for the second product.
    mock_confidence.side_effect = [0.2, 0.9]

    low = SimpleNamespace(id="PRD_LOW", seller_id=1, price=1000.0)
    high = SimpleNamespace(id="PRD_HIGH", seller_id=2, price=1000.0)

    result = rank_candidates([low, high], original_price=1000.0)

    assert [r["product_id"] for r in result] == ["PRD_HIGH", "PRD_LOW"]


@patch("app.fulfilment.ranking.SellerReliabilityService.get_response_rate")
@patch("app.fulfilment.ranking.SellerReliabilityService.get_score")
@patch("app.fulfilment.ranking.InventoryConfidenceService.get_score_for_product")
def test_rank_candidates_breaks_ties_on_lower_price(
    mock_confidence, mock_reliability, mock_response_rate
):
    mock_confidence.return_value = 0.5
    mock_reliability.return_value = 0.5
    mock_response_rate.return_value = 0.5

    expensive = SimpleNamespace(id="PRD_EXPENSIVE", seller_id=1, price=1000.0)
    cheap = SimpleNamespace(id="PRD_CHEAP", seller_id=2, price=900.0)

    result = rank_candidates([expensive, cheap], original_price=1000.0)

    assert [r["product_id"] for r in result] == ["PRD_CHEAP", "PRD_EXPENSIVE"]
