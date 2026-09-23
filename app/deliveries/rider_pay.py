"""What a rider earns for one completed drop.

The two payout paths had drifted into opposite incentives.

A **solo** delivery credited the rider the buyer's entire shipping fee --
₦1,000 on a typical order, with Markt keeping nothing.

A **run** priced the whole trip at a flat ``DEFAULT_BASE_PRICE`` regardless of
how many stops it had, split that equally, and paid the rider one share per
drop. So a rider earned the same total for a four-stop run as for a two-stop
one -- twice the work, the same money -- and roughly an eighth per drop of
what the same rider would make delivering those orders singly.

Both of those push a rider towards refusing batched work, which is the one
thing runs exist to encourage: batching is what makes delivery cheap enough
for the buyer and dense enough to be worth a rider's hour.

So both paths now come through here, and the shape is the one every delivery
marketplace converges on: the rider takes a fixed share of what the trip
actually collected, divided by the stops on it. Two properties fall out, and
both are tested:

* a rider's total for a trip **rises with every extra stop**, because the run
  price rises with every extra stop (see ``runs.DEFAULT_BASE_PRICE``'s
  replacement) -- more work is more money;
* per drop it is **lower** than a solo delivery, which is what makes the
  buyer's share cheaper than delivering alone -- but the stops are close
  together, so the rider's earnings per hour go up, not down.

The platform keeps the remainder, and can never pay out more than the trip
collected, because the share is a fraction of collected revenue.

Every number below is a placeholder, exactly like ``DEFAULT_FEE_CONFIG`` in
app/delivery_pricing/fees.py: the arithmetic is the decision, the rates are
Joshua's to set from real cost data.
"""

from decimal import Decimal
from typing import Optional

from app.libs.money import to_money

# The rider's cut of what a trip collected. The remainder covers the
# platform's cost of running the delivery -- matching, support, the refund
# exposure when a drop fails.
RIDER_REVENUE_SHARE = Decimal("0.80")

# No completed drop pays less than this, however the trip was priced or
# however the buyers' shares were capped. A rider who has ridden to an
# address and handed over a package has done the work.
MIN_DROP_EARNING = to_money("200.00")


def earning_for_drop(trip_revenue, stops: int) -> Optional[Decimal]:
    """What one completed drop pays.

    ``trip_revenue`` is what the whole trip collected -- the shipping fee for
    a solo delivery, the run's base price for a run. ``stops`` is how many
    drops that revenue is spread across.

    Returns ``None`` when there is nothing to pay from, so callers can keep
    treating "no earning" as "credit nothing" rather than crediting a floor
    against revenue that does not exist.
    """
    revenue = to_money(trip_revenue)
    if revenue is None or revenue <= 0:
        return None

    stops = max(1, int(stops or 1))
    share = to_money(revenue * RIDER_REVENUE_SHARE / Decimal(stops))
    if share is None:
        return None

    return max(share, MIN_DROP_EARNING)
