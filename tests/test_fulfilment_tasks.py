"""Tests for the fulfilment-allocation timeout task."""

from unittest.mock import patch

from app.fulfilment.tasks import expire_stale_allocations


@patch("app.fulfilment.services.FulfilmentService.expire_stale_allocations")
def test_expire_stale_allocations_task_delegates_to_service(mock_expire):
    mock_expire.return_value = {"timed_out": 3}

    result = expire_stale_allocations()

    assert result == {"timed_out": 3}
    mock_expire.assert_called_once()
