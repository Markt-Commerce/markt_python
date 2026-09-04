"""Checkout fee calculation (11): the buyer-facing Service Fee, the
opt-in Reliability Fee estimate, and the itemised breakdown / capture-
ceiling figures required by 11.4-11.5.

Used by the payment-first checkout flow
(PaymentService.initialize_checkout_payment). The pre-existing order-first
flow (CartService.checkout_cart) is untouched and keeps its own
placeholder shipping/tax math -- fixing that is a separate decision, not
bundled into this module.
"""

from decimal import Decimal
from typing import Any, Dict

from app.libs.money import to_money

# Rates and money literals are Decimal so they compose with the Decimal
# amounts coming off NUMERIC(12,2) columns. A float here would raise
# TypeError on contact -- which is the point: it makes an accidental
# float-in-money-math impossible to merge rather than silently lossy.

# 11.3 / Phase 0 decision.
SERVICE_FEE_RATE = Decimal("0.025")
SERVICE_FEE_FLOOR = Decimal("25.00")
SERVICE_FEE_CEILING = Decimal("1000.00")

# 11.2 / Phase 0 decision.
RELIABILITY_FEE_RATE = Decimal("0.10")
RELIABILITY_FEE_CEILING = Decimal("1500.00")

# 11.4: permitted AUTO price variation before requiring ASK approval
# (Phase 0 decision).
SUBSTITUTION_HEADROOM_RATE = Decimal("0.05")

ZERO = Decimal("0.00")


def calculate_service_fee(subtotal) -> Decimal:
    """11.3: a capped percentage -- floor so tiny orders still cover
    cost, ceiling so large baskets don't feel gouged."""
    subtotal = to_money(subtotal) or ZERO
    if subtotal <= 0:
        return ZERO
    fee = subtotal * SERVICE_FEE_RATE
    return to_money(min(max(fee, SERVICE_FEE_FLOOR), SERVICE_FEE_CEILING))


def calculate_reliability_fee_estimate(subtotal) -> Decimal:
    """11.2: 10% of order value, capped flat. This is an ESTIMATE shown
    to the buyer at checkout for transparency -- it must never be added
    into the captured total. It's only actually charged if a reroute
    fires, and rerouting doesn't exist yet (Phase 6)."""
    subtotal = to_money(subtotal) or ZERO
    if subtotal <= 0:
        return ZERO
    return to_money(min(subtotal * RELIABILITY_FEE_RATE, RELIABILITY_FEE_CEILING))


def calculate_capture_ceiling(
    subtotal,
    shipping_fee,
    service_fee,
    reliability_fee_opted_in: bool,
) -> Decimal:
    """11.4: the max the buyer could ever be charged today, covering the
    permitted substitution headroom plus the reliability fee if toggled.

    There's no auth/capture split (Phase 0: full capture immediately at
    checkout), so this figure is informational -- shown to the buyer for
    transparency about worst case -- rather than a PSP-level authorization
    hold."""
    subtotal = to_money(subtotal) or ZERO
    shipping_fee = to_money(shipping_fee) or ZERO
    service_fee = to_money(service_fee) or ZERO
    item_headroom = to_money(subtotal * SUBSTITUTION_HEADROOM_RATE)
    ceiling = subtotal + item_headroom + shipping_fee + service_fee
    if reliability_fee_opted_in:
        ceiling += calculate_reliability_fee_estimate(subtotal)
    return to_money(ceiling)


def build_fee_breakdown(
    subtotal,
    shipping_fee,
    reliability_fee_opted_in: bool = False,
    delivery_count: int = 1,
) -> Dict[str, Any]:
    """11.5: every component itemised and visible before payment.

    `total` is what's actually captured today (item prices + shipping +
    service fee only -- VAT is deferred per Phase 0, so no tax line, and
    the reliability fee is never captured, only estimated/toggled).
    `capture_ceiling` is the separate, larger figure for 11.4 transparency
    about the worst case if a reroute happens.

    `delivery_count` (1.1/7.3): how many separate delivery runs this cart
    needs -- one per distinct market among its sellers (see
    CartService.count_distinct_deliveries, which shipping_fee is already
    derived from). Passed through as its own field rather than making the
    client infer it from the shipping_fee number, so a multi-market
    basket can show a real, specific warning instead of guessing.
    """
    subtotal = to_money(subtotal) or ZERO
    shipping_fee = to_money(shipping_fee) or ZERO
    service_fee = calculate_service_fee(subtotal)
    reliability_fee_estimate = (
        calculate_reliability_fee_estimate(subtotal)
        if reliability_fee_opted_in
        else ZERO
    )
    total = to_money(subtotal + shipping_fee + service_fee)

    return {
        "subtotal": subtotal,
        "shipping_fee": shipping_fee,
        "delivery_count": delivery_count,
        "service_fee": service_fee,
        "reliability_fee_opted_in": reliability_fee_opted_in,
        "reliability_fee_estimate": reliability_fee_estimate,
        "total": total,
        "capture_ceiling": calculate_capture_ceiling(
            subtotal, shipping_fee, service_fee, reliability_fee_opted_in
        ),
    }
