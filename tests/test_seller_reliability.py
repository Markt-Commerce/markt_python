"""Unit tests for SellerReliabilityService: the §13.2 formula."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.fulfilment.models import FulfilmentAllocationStatus
from app.fulfilment.reliability import (
    DEFAULT_PRIOR,
    SCORE_VERSION,
    SellerReliabilityService,
    _response_time_decay,
)
from app.libs.errors import NotFoundError
from app.orders.models import OrderItem


def test_response_time_decay_full_score_for_instant_response():
    assert _response_time_decay(0) == 1.0


def test_response_time_decay_zero_at_full_window():
    window_seconds = 3 * 60  # SELLER_RESPONSE_TIMEOUT_MINUTES
    assert _response_time_decay(window_seconds) == 0.0
    assert _response_time_decay(window_seconds + 100) == 0.0


def test_response_time_decay_midway():
    window_seconds = 3 * 60
    assert _response_time_decay(window_seconds / 2) == pytest.approx(0.5)


def test_acceptance_and_response_rate_none_when_nothing_resolved():
    acceptance, response_rate = SellerReliabilityService._acceptance_and_response_rate(
        {}
    )
    assert acceptance is None
    assert response_rate is None


def test_acceptance_and_response_rate_combines_accepted_and_preparing():
    counts = {
        FulfilmentAllocationStatus.ACCEPTED: 3,
        FulfilmentAllocationStatus.PREPARING: 2,
        FulfilmentAllocationStatus.DECLINED: 1,
        FulfilmentAllocationStatus.TIMEOUT: 4,
    }
    acceptance, response_rate = SellerReliabilityService._acceptance_and_response_rate(
        counts
    )
    # accepted-like = 5, resolved = 10
    assert acceptance == 0.5
    # responded (accepted-like + declined) = 6 / 10
    assert response_rate == 0.6


def test_fulfilment_rate_none_when_no_accepted_allocations():
    session = MagicMock()
    session.query.return_value.join.return_value.filter.return_value.all.return_value = (
        []
    )

    result = SellerReliabilityService._fulfilment_rate(
        session, seller_id=7, cutoff=datetime.utcnow()
    )

    assert result is None


def test_fulfilment_rate_computes_delivered_fraction():
    session = MagicMock()
    rows = [
        (OrderItem.Status.DELIVERED,),
        (OrderItem.Status.DELIVERED,),
        (OrderItem.Status.CANCELLED,),
        (OrderItem.Status.PROCESSING,),
    ]
    session.query.return_value.join.return_value.filter.return_value.all.return_value = (
        rows
    )

    result = SellerReliabilityService._fulfilment_rate(
        session, seller_id=7, cutoff=datetime.utcnow()
    )

    assert result == 0.5


def test_response_time_component_none_when_no_responses():
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []

    result = SellerReliabilityService._response_time_component(
        session, seller_id=7, cutoff=datetime.utcnow()
    )

    assert result is None


def test_response_time_component_averages_decay_scores():
    now = datetime.utcnow()
    session = MagicMock()
    rows = [
        (now, now),  # instant -> 1.0
        (now, now + timedelta(minutes=3)),  # full window -> 0.0
    ]
    session.query.return_value.filter.return_value.all.return_value = rows

    result = SellerReliabilityService._response_time_component(
        session, seller_id=7, cutoff=now
    )

    assert result == pytest.approx(0.5)


@patch.object(SellerReliabilityService, "_response_time_component")
@patch.object(SellerReliabilityService, "_fulfilment_rate")
@patch.object(SellerReliabilityService, "_status_counts")
@patch("app.fulfilment.reliability.session_scope")
def test_calculate_score_combines_weighted_components(
    mock_scope, mock_counts, mock_fulfilment, mock_response_time
):
    seller = SimpleNamespace(id=7)
    session = MagicMock()
    session.query.return_value.get.return_value = seller
    session.query.return_value.filter_by.return_value.first.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    mock_counts.return_value = {
        FulfilmentAllocationStatus.ACCEPTED: 8,
        FulfilmentAllocationStatus.DECLINED: 1,
        FulfilmentAllocationStatus.TIMEOUT: 1,
    }
    mock_fulfilment.return_value = 0.9
    mock_response_time.return_value = 0.8

    record = SellerReliabilityService.calculate_score(7)

    # acceptance=0.8, response_rate=0.9, fulfilment=0.9,
    # inventory_accuracy=DEFAULT_PRIOR(0.6), response_time=0.8
    expected = round(
        0.30 * 0.8 + 0.20 * 0.9 + 0.20 * 0.9 + 0.15 * DEFAULT_PRIOR + 0.15 * 0.8, 4
    )
    assert record.score == expected
    assert record.score_version == SCORE_VERSION
    session.add.assert_called_once_with(record)


@patch.object(SellerReliabilityService, "_response_time_component")
@patch.object(SellerReliabilityService, "_fulfilment_rate")
@patch.object(SellerReliabilityService, "_status_counts")
@patch("app.fulfilment.reliability.session_scope")
def test_calculate_score_falls_back_to_prior_for_quiet_seller(
    mock_scope, mock_counts, mock_fulfilment, mock_response_time
):
    seller = SimpleNamespace(id=7)
    session = MagicMock()
    session.query.return_value.get.return_value = seller
    session.query.return_value.filter_by.return_value.first.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    mock_counts.return_value = {}
    mock_fulfilment.return_value = None
    mock_response_time.return_value = None

    record = SellerReliabilityService.calculate_score(7)

    assert record.score == DEFAULT_PRIOR


@patch("app.fulfilment.reliability.session_scope")
def test_calculate_score_raises_not_found_for_missing_seller(mock_scope):
    session = MagicMock()
    session.query.return_value.get.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(NotFoundError):
        SellerReliabilityService.calculate_score(999)


@patch.object(SellerReliabilityService, "_response_time_component")
@patch.object(SellerReliabilityService, "_fulfilment_rate")
@patch.object(SellerReliabilityService, "_status_counts")
@patch("app.fulfilment.reliability.session_scope")
def test_calculate_score_updates_existing_record_in_place(
    mock_scope, mock_counts, mock_fulfilment, mock_response_time
):
    seller = SimpleNamespace(id=7)
    existing = SimpleNamespace(
        score=0.1,
        acceptance_rate_component=0.1,
        response_rate_component=0.1,
        fulfilment_rate_component=0.1,
        inventory_accuracy_component=0.1,
        response_time_component=0.1,
        score_version=0,
        calculated_at=datetime.utcnow() - timedelta(days=1),
    )
    session = MagicMock()
    session.query.return_value.get.return_value = seller
    session.query.return_value.filter_by.return_value.first.return_value = existing
    mock_scope.return_value.__enter__.return_value = session

    mock_counts.return_value = {}
    mock_fulfilment.return_value = None
    mock_response_time.return_value = None

    record = SellerReliabilityService.calculate_score(7)

    assert record is existing
    session.add.assert_not_called()


@patch("app.fulfilment.reliability.session_scope")
def test_get_score_returns_prior_when_unscored(mock_scope):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    assert SellerReliabilityService.get_score(7) == DEFAULT_PRIOR


@patch("app.fulfilment.reliability.session_scope")
def test_get_score_returns_existing_score(mock_scope):
    existing = SimpleNamespace(score=0.77)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = existing
    mock_scope.return_value.__enter__.return_value = session

    assert SellerReliabilityService.get_score(7) == 0.77
