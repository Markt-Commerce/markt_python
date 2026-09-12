"""Splitting one delivery run's cost across the buyers who shared it.

Designed in docs/ADR-002-batch-delivery.md. Read its amendment first: Paystack
will not hold naira, so the hold-the-ceiling-capture-the-actual mechanism that
ADR chose is unavailable here and the money comes back as a refund instead.
That changes when the buyer is made whole, not how much they owe -- which is
what this module computes.

Three rules, in order of who they protect:

  1. **Sharing can never cost more than going alone.** Every share is capped
     at that buyer's own solo quote. This is the promise the batch opt-in is
     sold on, and it is the only rule here that is allowed to lose Markt
     money.
  2. **Markt never collects more than the run actually cost.** A batch is a
     saving passed on, not a margin.
  3. **Not one kobo goes missing.** An indivisible remainder goes to the
     earliest joiners rather than being rounded away, because rounding a
     fraction of a kobo per order is how ledgers stop balancing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from decouple import config

logger = logging.getLogger(__name__)


def batch_enabled() -> bool:
    """Whether batched delivery is offered at all.

    Off by default. The money model is only half the feature -- a buyer has to
    be told what is happening to their money before they agree to it -- so it
    stays behind a flag until the whole thing is there.
    """
    return config("DELIVERY_BATCH_ENABLED", default=False, cast=bool)


@dataclass(frozen=True)
class Participant:
    """One order sharing a run.

    `solo_fee_minor` is what this buyer was quoted to go alone, captured at
    checkout. It is the ceiling, and it has to be recorded then because after
    a run closes there is no way to work out what going alone would have cost.
    """

    order_id: str
    solo_fee_minor: int
    joined_at: Optional[datetime] = None


@dataclass(frozen=True)
class Share:
    order_id: str
    charged_minor: int
    solo_fee_minor: int
    #: True when this buyer's share was held down to their solo quote, i.e.
    #: the batch would otherwise have cost them more than going alone.
    capped: bool

    @property
    def saved_minor(self) -> int:
        return self.solo_fee_minor - self.charged_minor


@dataclass(frozen=True)
class Settlement:
    shares: Tuple[Share, ...]
    run_cost_minor: int
    collected_minor: int

    @property
    def absorbed_minor(self) -> int:
        """What Markt is paying because capping held shares down.

        Deliberately surfaced rather than hidden in a rounding difference: it
        is the real cost of the "never more than going alone" promise, and if
        it is large the run was priced wrong or filled too thinly.
        """
        return max(self.run_cost_minor - self.collected_minor, 0)


def split(participants: Sequence[Participant], run_cost_minor: int) -> Settlement:
    """Divide a run's cost. Pure: no database, no clock.

    Equal shares, with the indivisible remainder going to whoever joined
    first. That direction is deliberate. Somebody has to carry the odd kobo,
    and giving it to the earliest joiner is both explainable and the least
    unfair reading -- they had the longest use of the run and the most chance
    to leave before it closed.
    """
    if not participants:
        return Settlement(shares=(), run_cost_minor=run_cost_minor, collected_minor=0)
    if run_cost_minor < 0:
        raise ValueError("A delivery run cannot cost a negative amount")

    # Earliest first. A participant with no join time sorts last rather than
    # blowing up: an unknown join time should not win the tie-break.
    ordered = sorted(
        participants,
        key=lambda p: (p.joined_at is None, p.joined_at or datetime.max),
    )

    n = len(ordered)
    base, remainder = divmod(run_cost_minor, n)

    shares: List[Share] = []
    for index, participant in enumerate(ordered):
        owed = base + (1 if index < remainder else 0)
        charged = min(owed, participant.solo_fee_minor)
        shares.append(
            Share(
                order_id=participant.order_id,
                charged_minor=charged,
                solo_fee_minor=participant.solo_fee_minor,
                capped=charged < owed,
            )
        )

    return Settlement(
        shares=tuple(shares),
        run_cost_minor=run_cost_minor,
        collected_minor=sum(s.charged_minor for s in shares),
    )


def settle_run(session, delivery_run_id: str) -> Optional[Settlement]:
    """Work out and record what each buyer in a run actually owes.

    Takes a row lock on the run and does everything inside it. Joining and
    leaving a run both change every other participant's share, so two of those
    landing at once against an unlocked run would each compute a split from a
    roster the other was already changing, and the last writer would win with
    numbers nobody agreed to.

    Idempotent: a delivery that is already settled keeps the figure it has.
    Settlement is what the buyer was told they owe, and recomputing it later --
    after a refund has gone out on the strength of it -- would silently
    disagree with money that has already moved.
    """
    from app.deliveries.models import DeliveryRun, DeliveryRunOrder

    from .order_delivery import OrderDelivery

    run = (
        session.query(DeliveryRun)
        .filter(DeliveryRun.id == delivery_run_id)
        .with_for_update()
        .first()
    )
    if run is None:
        return None

    rows = (
        session.query(DeliveryRunOrder, OrderDelivery)
        .join(OrderDelivery, OrderDelivery.order_id == DeliveryRunOrder.order_id)
        .filter(DeliveryRunOrder.delivery_run_id == delivery_run_id)
        .all()
    )
    if not rows:
        return None

    participants = [
        Participant(
            order_id=delivery.order_id,
            solo_fee_minor=delivery.solo_fee_minor,
            joined_at=run_order.joined_at,
        )
        for run_order, delivery in rows
    ]

    # base_price is the whole run; price_per_order is its naive equal split and
    # is not used here, because it knows nothing about anybody's solo ceiling.
    from app.libs.money import to_subunit

    run_cost_minor = to_subunit(run.base_price or 0)

    settlement = split(participants, run_cost_minor)
    by_order = {s.order_id: s for s in settlement.shares}

    for _, delivery in rows:
        share = by_order.get(delivery.order_id)
        if share is None:
            continue
        if delivery.is_settled:
            continue
        delivery.settled_fee_minor = share.charged_minor

    logger.info(
        "Run %s settled: %s orders, cost %s kobo, collected %s, Markt absorbs %s",
        delivery_run_id,
        len(settlement.shares),
        settlement.run_cost_minor,
        settlement.collected_minor,
        settlement.absorbed_minor,
    )
    return settlement
