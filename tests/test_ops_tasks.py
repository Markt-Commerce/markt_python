"""Tests for the generic stuck-order recovery coordinator (14.3):
app.ops.tasks.recover_stuck_orders re-runs every existing recovery/expiry
worker function directly, isolating failures so one broken sub-sweep
can't stop the others."""

from unittest.mock import patch

from app.ops.tasks import recover_stuck_orders


@patch("app.deliveries.runs.DeliveryRunService.close_runs_past_cutoff")
@patch("app.payments.tasks.expire_abandoned_checkout_payments")
@patch("app.orders.tasks.expire_unpaid_orders")
@patch("app.inventory.tasks.expire_stale_reservations")
@patch("app.fulfilment.tasks.recover_stuck_fulfilment_allocations")
@patch("app.fulfilment.tasks.expire_stale_buyer_approvals")
@patch("app.fulfilment.tasks.expire_stale_allocations")
def test_recover_stuck_orders_runs_every_sub_sweep(
    mock_seller_timeout,
    mock_buyer_approval,
    mock_fulfilment_deadline,
    mock_reservation_expiry,
    mock_unpaid_orders,
    mock_payment_reconciliation,
    mock_delivery_window_close,
):
    mock_seller_timeout.return_value = {"timed_out": 1}
    mock_buyer_approval.return_value = {"timed_out": 0}
    mock_fulfilment_deadline.return_value = {
        "retried": 2,
        "resolved_stuck_rerouting": 0,
    }
    mock_reservation_expiry.return_value = {"expired": 3}
    mock_unpaid_orders.return_value = {"expired": 1}
    mock_payment_reconciliation.return_value = {"expired": 0}
    mock_delivery_window_close.return_value = {
        "closed": 1,
        "cancelled_empty": 0,
        "free_cancellations": 0,
    }

    result = recover_stuck_orders()

    assert result["failures"] == 0
    assert result["sub_sweeps"]["seller_timeout"] == {"timed_out": 1}
    assert result["sub_sweeps"]["buyer_approval_timeout"] == {"timed_out": 0}
    assert result["sub_sweeps"]["fulfilment_deadline_recovery"] == {
        "retried": 2,
        "resolved_stuck_rerouting": 0,
    }
    assert result["sub_sweeps"]["reservation_expiry"] == {"expired": 3}
    assert result["sub_sweeps"]["unpaid_order_expiry"] == {"expired": 1}
    assert result["sub_sweeps"]["payment_reconciliation"] == {"expired": 0}
    assert result["sub_sweeps"]["delivery_window_close"] == {
        "closed": 1,
        "cancelled_empty": 0,
        "free_cancellations": 0,
    }
    for mock in (
        mock_seller_timeout,
        mock_buyer_approval,
        mock_fulfilment_deadline,
        mock_reservation_expiry,
        mock_unpaid_orders,
        mock_payment_reconciliation,
        mock_delivery_window_close,
    ):
        mock.assert_called_once()


@patch("app.deliveries.runs.DeliveryRunService.close_runs_past_cutoff")
@patch("app.payments.tasks.expire_abandoned_checkout_payments")
@patch("app.orders.tasks.expire_unpaid_orders")
@patch("app.inventory.tasks.expire_stale_reservations")
@patch("app.fulfilment.tasks.recover_stuck_fulfilment_allocations")
@patch("app.fulfilment.tasks.expire_stale_buyer_approvals")
@patch("app.fulfilment.tasks.expire_stale_allocations")
def test_recover_stuck_orders_isolates_one_failing_sub_sweep(
    mock_seller_timeout,
    mock_buyer_approval,
    mock_fulfilment_deadline,
    mock_reservation_expiry,
    mock_unpaid_orders,
    mock_payment_reconciliation,
    mock_delivery_window_close,
):
    mock_seller_timeout.side_effect = Exception("boom")
    mock_buyer_approval.return_value = {"timed_out": 0}
    mock_fulfilment_deadline.return_value = {
        "retried": 0,
        "resolved_stuck_rerouting": 0,
    }
    mock_reservation_expiry.return_value = {"expired": 0}
    mock_unpaid_orders.return_value = {"expired": 0}
    mock_payment_reconciliation.return_value = {"expired": 0}
    mock_delivery_window_close.return_value = {
        "closed": 0,
        "cancelled_empty": 0,
        "free_cancellations": 0,
    }

    result = recover_stuck_orders()

    assert result["failures"] == 1
    assert result["sub_sweeps"]["seller_timeout"] == {"error": "boom"}
    # The other six sub-sweeps still ran despite the one failure.
    assert result["sub_sweeps"]["buyer_approval_timeout"] == {"timed_out": 0}
    mock_buyer_approval.assert_called_once()
    mock_fulfilment_deadline.assert_called_once()
    mock_reservation_expiry.assert_called_once()
    mock_unpaid_orders.assert_called_once()
    mock_payment_reconciliation.assert_called_once()
    mock_delivery_window_close.assert_called_once()
