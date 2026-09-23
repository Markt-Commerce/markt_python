"""One rider, several shops, one buyer.

Markt's baskets routinely span two shops that are a few hundred metres apart
-- two stalls in the same market, two units on the same campus road. Charging
two full delivery fees for that is charging twice for one trip, and a buyer
can see it is one trip.

So: when the pickups are close enough to be collected on the way, price the
whole thing as the single journey it is and split what is saved between the
orders.

This deliberately reuses the batch money model rather than inventing a second
one. Batching shares a run between several *dropoffs*; this shares one
between several *pickups*. The rules that matter are identical -- nobody pays
more than they would alone, Markt never collects more than the trip costs, no
kobo goes missing -- so they live in one place and are tested once.

What is different is the allocation. A batch splits equally because every
buyer is getting the same thing: a delivery to their door. Here they are not:
one order's shop may be a kilometre from the buyer and another's six. Equal
shares would have the near order subsidising the far one, so the split is
proportional to what each would have cost alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from decouple import config

from app.libs.geo import haversine_km

logger = logging.getLogger(__name__)


def max_pickup_spread_km() -> float:
    """How far apart two shops can be and still share one collection.

    Not a routing decision -- a rider makes that. This is the line past which
    "on the way" stops being true and the second pickup becomes a detour
    somebody has to be paid for.
    """
    return config("DELIVERY_COMBINE_RADIUS_KM", default=1.5, cast=float)


@dataclass(frozen=True)
class Pickup:
    """One shop's leg of a combined delivery."""

    seller_id: int
    lat: float
    lng: float
    #: What this order's delivery costs on its own. The ceiling its share is
    #: capped at, and the weight used to divide the shared fee.
    solo_fee_minor: int


@dataclass(frozen=True)
class PickupShare:
    seller_id: int
    charged_minor: int
    solo_fee_minor: int

    @property
    def saved_minor(self) -> int:
        return self.solo_fee_minor - self.charged_minor


@dataclass(frozen=True)
class CombinedQuote:
    shares: Tuple[PickupShare, ...]
    combined_fee_minor: int
    separate_fee_minor: int

    @property
    def saved_minor(self) -> int:
        return max(self.separate_fee_minor - self.combined_fee_minor, 0)

    @property
    def worth_offering(self) -> bool:
        """Only offer it when it actually saves the buyer money.

        A combined trip that costs the same is a worse deal than it looks --
        it ties two orders to one rider's schedule for nothing -- so it is
        not offered at all.
        """
        return self.saved_minor > 0


def can_combine(pickups: Sequence[Pickup]) -> bool:
    """Whether these shops are close enough to collect in one go.

    Every pair must be within the spread, not just consecutive ones. Three
    shops in a line, each 1.4km from the next, are 2.8km end to end -- which
    is a detour however you order the stops.
    """
    if len(pickups) < 2:
        return False
    limit = max_pickup_spread_km()
    for i, a in enumerate(pickups):
        for j in range(i + 1, len(pickups)):
            b = pickups[j]
            if haversine_km(a.lat, a.lng, b.lat, b.lng) > limit:
                return False
    return True


def allocate(pickups: Sequence[Pickup], combined_fee_minor: int) -> CombinedQuote:
    """Divide a shared trip's fee between the orders sharing it.

    Proportional to what each order would have paid alone, so the shop next
    door does not subsidise the one across town, then capped at that solo fee
    so sharing can never cost more than going alone.

    Pure: no database, no clock.
    """
    if not pickups:
        raise ValueError("A combined delivery needs at least one pickup")
    if combined_fee_minor < 0:
        raise ValueError("A delivery cannot cost a negative amount")

    separate = sum(p.solo_fee_minor for p in pickups)
    ordered = sorted(pickups, key=lambda p: p.seller_id)

    if separate <= 0:
        # Every leg is free, so there is nothing to divide and nothing to
        # charge. Guards the division below.
        return CombinedQuote(
            shares=tuple(
                PickupShare(p.seller_id, 0, p.solo_fee_minor) for p in ordered
            ),
            combined_fee_minor=combined_fee_minor,
            separate_fee_minor=separate,
        )

    # Largest-remainder, so the kobo that do not divide are handed to the
    # orders with the strongest claim to them rather than rounded away.
    exact = [(p, combined_fee_minor * p.solo_fee_minor / separate) for p in ordered]
    floors = [(p, int(v)) for p, v in exact]
    leftover = combined_fee_minor - sum(v for _, v in floors)
    remainders = sorted(
        range(len(exact)),
        key=lambda i: (-(exact[i][1] - floors[i][1]), ordered[i].seller_id),
    )
    amounts = {p.seller_id: v for p, v in floors}
    for i in remainders[:leftover]:
        amounts[ordered[i].seller_id] += 1

    shares: List[PickupShare] = []
    for p in ordered:
        charged = min(amounts[p.seller_id], p.solo_fee_minor)
        shares.append(PickupShare(p.seller_id, charged, p.solo_fee_minor))

    return CombinedQuote(
        shares=tuple(shares),
        combined_fee_minor=combined_fee_minor,
        separate_fee_minor=separate,
    )
