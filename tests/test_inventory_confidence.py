"""Unit tests for InventoryConfidenceService: the 8.3 formula, 8.4
cold-start prior, and confidence-band gating."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.inventory.confidence import (
    ConfidenceBand,
    DEFAULT_PRIOR,
    HIGH_THRESHOLD,
    MEDIUM_THRESHOLD,
    InventoryConfidenceService,
    get_confidence_band,
)
from app.libs.errors import NotFoundError, ValidationError
from app.orders.models import OrderItem


def _session(
    *,
    product=None,
    product_category=None,
    prior=None,
    fulfilment_rows=None,
    activity_max=None,
    existing_score=None,
):
    session = MagicMock()

    def query_side_effect(*args):
        target = args[0]
        name = getattr(target, "__name__", None)
        mock = MagicMock()
        if name == "Product":
            mock.get.return_value = product
        elif name == "ProductCategory":
            mock.filter_by.return_value.first.return_value = product_category
        elif name == "CategoryConfidencePrior":
            mock.filter_by.return_value.first.return_value = prior
        elif name == "InventoryConfidenceScore":
            mock.filter_by.return_value.first.return_value = existing_score
        elif len(args) == 2:
            # session.query(OrderItem.status, func.count(OrderItem.id)) -- fulfilment
            mock.filter.return_value.group_by.return_value.all.return_value = (
                fulfilment_rows or []
            )
        else:
            # session.query(func.max(OrderItem.created_at)) -- activity
            mock.filter.return_value.scalar.return_value = activity_max
        return mock

    session.query.side_effect = query_side_effect
    return session


def test_get_confidence_band_thresholds():
    assert get_confidence_band(HIGH_THRESHOLD) == ConfidenceBand.HIGH
    assert get_confidence_band(0.99) == ConfidenceBand.HIGH
    assert get_confidence_band(HIGH_THRESHOLD - 0.01) == ConfidenceBand.MEDIUM
    assert get_confidence_band(MEDIUM_THRESHOLD) == ConfidenceBand.MEDIUM
    assert get_confidence_band(MEDIUM_THRESHOLD - 0.01) == ConfidenceBand.LOW
    assert get_confidence_band(0.0) == ConfidenceBand.LOW


def test_get_category_prior_uses_primary_category_prior():
    product_category = SimpleNamespace(category_id=5)
    prior = SimpleNamespace(prior_score=0.5)
    session = _session(product_category=product_category, prior=prior)

    assert InventoryConfidenceService.get_category_prior(session, "PRD_1") == 0.5


def test_get_category_prior_falls_back_to_default_when_category_has_no_prior():
    product_category = SimpleNamespace(category_id=5)
    session = _session(product_category=product_category, prior=None)

    assert (
        InventoryConfidenceService.get_category_prior(session, "PRD_1") == DEFAULT_PRIOR
    )


def test_get_category_prior_falls_back_to_default_when_no_category():
    session = _session(product_category=None)

    assert (
        InventoryConfidenceService.get_category_prior(session, "PRD_1") == DEFAULT_PRIOR
    )


def test_seed_category_prior_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        InventoryConfidenceService.seed_category_prior(5, prior_score=1.5)


@patch("app.inventory.confidence.session_scope")
def test_seed_category_prior_creates_when_absent(mock_scope):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    InventoryConfidenceService.seed_category_prior(5, prior_score=0.55)

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.category_id == 5
    assert added.prior_score == 0.55


@patch("app.inventory.confidence.session_scope")
def test_seed_category_prior_updates_when_present(mock_scope):
    existing = SimpleNamespace(category_id=5, prior_score=0.5)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = existing
    mock_scope.return_value.__enter__.return_value = session

    InventoryConfidenceService.seed_category_prior(5, prior_score=0.9)

    session.add.assert_not_called()
    assert existing.prior_score == 0.9


@patch("app.inventory.confidence.session_scope")
def test_calculate_score_combines_weighted_components(mock_scope):
    now = datetime.utcnow()
    product = SimpleNamespace(
        id="PRD_1", seller_id=99, updated_at=now - timedelta(hours=12)
    )
    product_category = SimpleNamespace(category_id=5)
    prior = SimpleNamespace(prior_score=0.5)
    session = _session(
        product=product,
        product_category=product_category,
        prior=prior,
        fulfilment_rows=[
            (OrderItem.Status.DELIVERED, 8),
            (OrderItem.Status.CANCELLED, 2),
        ],
        activity_max=now - timedelta(hours=12),
        existing_score=None,
    )
    mock_scope.return_value.__enter__.return_value = session

    record = InventoryConfidenceService.calculate_score("PRD_1")

    # recency=1.0 (12h old), accuracy=prior=0.5, fulfilment=8/10=0.8, activity=1.0
    # 0.40*1.0 + 0.30*0.5 + 0.20*0.8 + 0.10*1.0 = 0.81
    assert record.score == pytest.approx(0.81)
    assert record.recency_component == pytest.approx(1.0)
    assert record.accuracy_component == pytest.approx(0.5)
    assert record.fulfilment_component == pytest.approx(0.8)
    assert record.activity_component == pytest.approx(1.0)
    session.add.assert_called_once_with(record)


@patch("app.inventory.confidence.session_scope")
def test_calculate_score_falls_back_to_prior_for_seller_with_no_resolved_items(
    mock_scope,
):
    now = datetime.utcnow()
    product = SimpleNamespace(id="PRD_1", seller_id=99, updated_at=now)
    product_category = SimpleNamespace(category_id=5)
    prior = SimpleNamespace(prior_score=0.5)
    session = _session(
        product=product,
        product_category=product_category,
        prior=prior,
        fulfilment_rows=[],
        activity_max=now,
        existing_score=None,
    )
    mock_scope.return_value.__enter__.return_value = session

    record = InventoryConfidenceService.calculate_score("PRD_1")

    assert record.fulfilment_component == pytest.approx(0.5)


@patch("app.inventory.confidence.session_scope")
def test_calculate_score_no_seller_scores_zero_activity(mock_scope):
    now = datetime.utcnow()
    product = SimpleNamespace(id="PRD_1", seller_id=None, updated_at=now)
    session = _session(product=product, product_category=None, existing_score=None)
    mock_scope.return_value.__enter__.return_value = session

    record = InventoryConfidenceService.calculate_score("PRD_1")

    assert record.activity_component == 0.0
    assert record.fulfilment_component == pytest.approx(DEFAULT_PRIOR)


@patch("app.inventory.confidence.session_scope")
def test_calculate_score_updates_existing_record_in_place(mock_scope):
    now = datetime.utcnow()
    product = SimpleNamespace(id="PRD_1", seller_id=None, updated_at=now)
    existing = SimpleNamespace(
        score=0.1,
        recency_component=0.1,
        accuracy_component=0.1,
        fulfilment_component=0.1,
        activity_component=0.1,
        calculated_at=now - timedelta(days=1),
    )
    session = _session(product=product, product_category=None, existing_score=existing)
    mock_scope.return_value.__enter__.return_value = session

    record = InventoryConfidenceService.calculate_score("PRD_1")

    assert record is existing
    session.add.assert_not_called()
    assert existing.score != 0.1


@patch("app.inventory.confidence.session_scope")
def test_get_score_for_product_uses_existing_score(mock_scope):
    existing = SimpleNamespace(score=0.85)
    session = _session(existing_score=existing)
    mock_scope.return_value.__enter__.return_value = session

    assert InventoryConfidenceService.get_score_for_product("PRD_1") == 0.85


@patch("app.inventory.confidence.session_scope")
def test_get_score_for_product_falls_back_to_prior_when_unscored(mock_scope):
    product_category = SimpleNamespace(category_id=5)
    prior = SimpleNamespace(prior_score=0.4)
    session = _session(
        existing_score=None, product_category=product_category, prior=prior
    )
    mock_scope.return_value.__enter__.return_value = session

    assert InventoryConfidenceService.get_score_for_product("PRD_1") == 0.4


@patch("app.inventory.confidence.session_scope")
def test_calculate_score_raises_not_found_for_missing_product(mock_scope):
    session = _session(product=None)
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(NotFoundError):
        InventoryConfidenceService.calculate_score("PRD_MISSING")


@patch("app.inventory.confidence.session_scope")
def test_get_band_for_product_uses_existing_score(mock_scope):
    existing = SimpleNamespace(score=0.85)
    session = _session(existing_score=existing)
    mock_scope.return_value.__enter__.return_value = session

    assert (
        InventoryConfidenceService.get_band_for_product("PRD_1") == ConfidenceBand.HIGH
    )


@patch("app.inventory.confidence.session_scope")
def test_get_band_for_product_falls_back_to_prior_when_unscored(mock_scope):
    product_category = SimpleNamespace(category_id=5)
    prior = SimpleNamespace(prior_score=0.1)
    session = _session(
        existing_score=None, product_category=product_category, prior=prior
    )
    mock_scope.return_value.__enter__.return_value = session

    assert (
        InventoryConfidenceService.get_band_for_product("PRD_1") == ConfidenceBand.LOW
    )
