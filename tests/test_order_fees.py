"""Unit tests for the checkout fee model (§11.2-11.5, Phase 0 decisions)."""

import pytest

from app.orders.fees import (
    RELIABILITY_FEE_CEILING,
    SERVICE_FEE_CEILING,
    SERVICE_FEE_FLOOR,
    build_fee_breakdown,
    calculate_capture_ceiling,
    calculate_reliability_fee_estimate,
    calculate_service_fee,
)


def test_service_fee_applies_floor_for_tiny_orders():
    # 2.5% of 500 = 12.50, below the ₦25 floor
    assert calculate_service_fee(500.0) == SERVICE_FEE_FLOOR


def test_service_fee_percentage_in_the_middle_band():
    assert calculate_service_fee(2000.0) == 50.0
    assert calculate_service_fee(30000.0) == 750.0


def test_service_fee_applies_ceiling_for_large_baskets():
    # 2.5% of 100,000 = 2,500, above the ₦1,000 ceiling
    assert calculate_service_fee(100000.0) == SERVICE_FEE_CEILING


def test_service_fee_zero_for_non_positive_subtotal():
    assert calculate_service_fee(0.0) == 0.0
    assert calculate_service_fee(-5.0) == 0.0


def test_reliability_fee_estimate_is_ten_percent():
    assert calculate_reliability_fee_estimate(5000.0) == 500.0


def test_reliability_fee_estimate_applies_flat_cap():
    # 10% of 30,000 = 3,000, above the ₦1,500 cap
    assert calculate_reliability_fee_estimate(30000.0) == RELIABILITY_FEE_CEILING


def test_capture_ceiling_excludes_reliability_fee_when_not_opted_in():
    ceiling = calculate_capture_ceiling(
        subtotal=1000.0,
        shipping_fee=10.0,
        service_fee=25.0,
        reliability_fee_opted_in=False,
    )
    # 1000 + 5% headroom(50) + 10 + 25
    assert ceiling == 1085.0


def test_capture_ceiling_includes_reliability_fee_when_opted_in():
    ceiling = calculate_capture_ceiling(
        subtotal=1000.0,
        shipping_fee=10.0,
        service_fee=25.0,
        reliability_fee_opted_in=True,
    )
    # 1085 (as above) + reliability estimate (10% of 1000 = 100)
    assert ceiling == 1185.0


def test_build_fee_breakdown_total_never_includes_reliability_fee():
    breakdown = build_fee_breakdown(1000.0, 10.0, reliability_fee_opted_in=True)

    assert breakdown["total"] == 1035.0  # subtotal + shipping + service fee only
    assert breakdown["reliability_fee_opted_in"] is True
    assert breakdown["reliability_fee_estimate"] == 100.0
    assert breakdown["capture_ceiling"] == 1185.0


def test_build_fee_breakdown_reliability_estimate_zero_when_not_opted_in():
    breakdown = build_fee_breakdown(1000.0, 10.0, reliability_fee_opted_in=False)

    assert breakdown["reliability_fee_estimate"] == 0.0
    assert breakdown["reliability_fee_opted_in"] is False
