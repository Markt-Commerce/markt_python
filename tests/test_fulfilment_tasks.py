"""Tests for the fulfilment-allocation timeout task and the scheduled
seller-reliability recompute task."""

from unittest.mock import MagicMock, patch

from app.fulfilment.tasks import (
    expire_stale_allocations,
    recompute_seller_reliability_scores,
)


@patch("app.fulfilment.services.FulfilmentService.expire_stale_allocations")
def test_expire_stale_allocations_task_delegates_to_service(mock_expire):
    mock_expire.return_value = {"timed_out": 3}

    result = expire_stale_allocations()

    assert result == {"timed_out": 3}
    mock_expire.assert_called_once()


@patch("app.fulfilment.reliability.SellerReliabilityService.calculate_score")
@patch("app.libs.session.session_scope")
def test_recompute_seller_reliability_scores_recomputes_every_active_seller(
    mock_session_scope, mock_calculate
):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.all.return_value = [
        (1,),
        (2,),
    ]
    mock_session_scope.return_value.__enter__.return_value = session

    result = recompute_seller_reliability_scores()

    assert result == {"recomputed": 2, "failed": 0}
    mock_calculate.assert_any_call(1)
    mock_calculate.assert_any_call(2)


@patch("app.fulfilment.reliability.SellerReliabilityService.calculate_score")
@patch("app.libs.session.session_scope")
def test_recompute_seller_reliability_scores_counts_failures(
    mock_session_scope, mock_calculate
):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.all.return_value = [
        (1,),
        (2,),
    ]
    mock_session_scope.return_value.__enter__.return_value = session
    mock_calculate.side_effect = [Exception("boom"), None]

    result = recompute_seller_reliability_scores()

    assert result == {"recomputed": 1, "failed": 1}
