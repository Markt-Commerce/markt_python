"""Checkout fee calculation (11): the buyer-facing Service Fee, the
opt-in Reliability Fee estimate, and the itemised breakdown / capture-
ceiling figures required by 11.4-11.5.

Used by the payment-first checkout flow
(PaymentService.initialize_checkout_payment). The pre-existing order-first
flow (CartService.checkout_cart) is untouched and keeps its own
placeholder shipping/tax math -- fixing that is a separate decision, not
bundled into this module.
"""

from typing import Any, Dict

# 11.3 / Phase 0 decision.
SERVICE_FEE_RATE = 0.025
SERVICE_FEE_FLOOR = 25.0
SERVICE_FEE_CEILING = 1000.0

# 11.2 / Phase 0 decision.
RELIABILITY_FEE_RATE = 0.10
RELIABILITY_FEE_CEILING = 1500.0

# 11.4: permitted AUTO price variation before requiring ASK approval
# (Phase 0 decision).
SUBSTITUTION_HEADROOM_RATE = 0.05


def calculate_service_fee(subtotal: float) -> float:
    """11.3: a capped percentage -- floor so tiny orders still cover
    cost, ceiling so large baskets don't feel gouged."""
    if subtotal <= 0:
        return 0.0
    fee = subtotal * SERVICE_FEE_RATE
    return round(min(max(fee, SERVICE_FEE_FLOOR), SERVICE_FEE_CEILING), 2)


def calculate_reliability_fee_estimate(subtotal: float) -> float:
    """11.2: 10% of order value, capped flat. This is an ESTIMATE shown
    to the buyer at checkout for transparency -- it must never be added
    into the captured total. It's only actually charged if a reroute
    fires, and rerouting doesn't exist yet (Phase 6)."""
    if subtotal <= 0:
        return 0.0
    return round(min(subtotal * RELIABILITY_FEE_RATE, RELIABILITY_FEE_CEILING), 2)


def calculate_capture_ceiling(
    subtotal: float,
    shipping_fee: float,
    service_fee: float,
    reliability_fee_opted_in: bool,
) -> float:
    """11.4: the max the buyer could ever be charged today, covering the
    permitted substitution headroom plus the reliability fee if toggled.

    There's no auth/capture split (Phase 0: full capture immediately at
    checkout), so this figure is informational -- shown to the buyer for
    transparency about worst case -- rather than a PSP-level authorization
    hold."""
    item_headroom = round(subtotal * SUBSTITUTION_HEADROOM_RATE, 2)
    ceiling = subtotal + item_headroom + shipping_fee + service_fee
    if reliability_fee_opted_in:
        ceiling += calculate_reliability_fee_estimate(subtotal)
    return round(ceiling, 2)


def build_fee_breakdown(
    subtotal: float,
    shipping_fee: float,
    reliability_fee_opted_in: bool = False,
) -> Dict[str, Any]:
    """11.5: every component itemised and visible before payment.

    `total` is what's actually captured today (item prices + shipping +
    service fee only -- VAT is deferred per Phase 0, so no tax line, and
    the reliability fee is never captured, only estimated/toggled).
    `capture_ceiling` is the separate, larger figure for 11.4 transparency
    about the worst case if a reroute happens.
    """
    service_fee = calculate_service_fee(subtotal)
    reliability_fee_estimate = (
        calculate_reliability_fee_estimate(subtotal)
        if reliability_fee_opted_in
        else 0.0
    )
    total = round(subtotal + shipping_fee + service_fee, 2)

    return {
        "subtotal": round(subtotal, 2),
        "shipping_fee": round(shipping_fee, 2),
        "service_fee": service_fee,
        "reliability_fee_opted_in": reliability_fee_opted_in,
        "reliability_fee_estimate": reliability_fee_estimate,
        "total": total,
        "capture_ceiling": calculate_capture_ceiling(
            subtotal, shipping_fee, service_fee, reliability_fee_opted_in
        ),
    }
