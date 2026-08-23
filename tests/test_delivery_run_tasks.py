"""Tests for the delivery-run batching Celery tasks (10.1-10.3)."""

from unittest.mock import patch

from app.deliveries.tasks import (
    attach_eligible_orders,
    close_runs_past_cutoff,
    notify_thin_volume_orders,
)


@patch("app.deliveries.runs.DeliveryRunService.attach_eligible_orders")
def test_attach_eligible_orders_task_delegates_to_service(mock_attach):
    mock_attach.return_value = {"attached": 2, "skipped_unresolved": 1}

    result = attach_eligible_orders()

    assert result == {"attached": 2, "skipped_unresolved": 1}
    mock_attach.assert_called_once()


@patch("app.deliveries.runs.DeliveryRunService.close_runs_past_cutoff")
def test_close_runs_past_cutoff_task_delegates_to_service(mock_close):
    mock_close.return_value = {
        "closed": 1,
        "cancelled_empty": 2,
        "free_cancellations": 3,
    }

    result = close_runs_past_cutoff()

    assert result == {"closed": 1, "cancelled_empty": 2, "free_cancellations": 3}
    mock_close.assert_called_once()


@patch("app.deliveries.runs.DeliveryRunService.notify_thin_volume_orders")
def test_notify_thin_volume_orders_task_delegates_to_service(mock_notify):
    mock_notify.return_value = {"notified": 4}

    result = notify_thin_volume_orders()

    assert result == {"notified": 4}
    mock_notify.assert_called_once()
