"""The fee engine.

A strategy interface with one config-driven implementation. The numbers below
are placeholders and are flagged as such -- real landmark and distance data
does not exist yet, and the point of this file is that acquiring it does not
change a single caller.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuoteContext:
    """Everything a strategy is allowed to price on.

    Deliberately not the cart or the order: a strategy that can reach into an
    order will eventually price on something that is not about delivery.
    """

    distance_km: float
    pickup_zone_id: int
    dropoff_zone_id: int
    lane_base_fee_minor: Optional[int] = None
    item_count: int = 1
    total_weight_grams: int = 0


@dataclass(frozen=True)
class FeeLine:
    """One named component of a fee, in kobo."""

    label: str
    amount_minor: int


@dataclass(frozen=True)
class FeeBreakdown:
    total_minor: int
    lines: List[FeeLine] = field(default_factory=list)

    def as_json(self) -> dict:
        return {
            "total_minor": self.total_minor,
            "lines": [
                {"label": line.label, "amount_minor": line.amount_minor}
                for line in self.lines
            ],
        }


class FeeStrategy(Protocol):
    name: str
    version: str

    def quote(self, ctx: QuoteContext) -> FeeBreakdown:  # pragma: no cover - protocol
        ...


# --- configuration ----------------------------------------------------------
# Placeholders, not real rates. Every one of these is a number somebody has to
# decide from real cost data; none is fabricated to look authoritative. They
# live here rather than in the strategy so they can move to the database or an
# env-backed config without touching the arithmetic.
DEFAULT_FEE_CONFIG = {
    # Charged on every delivery regardless of distance.
    "lane_base_minor": 50_000,  # ₦500.00
    # [min_km_inclusive, max_km_exclusive, surcharge_minor]
    "distance_bands": [
        [0.0, 3.0, 0],
        [3.0, 7.0, 20_000],  # ₦200.00
        [7.0, 15.0, 50_000],  # ₦500.00
    ],
    # Beyond the last band. A quote is still produced -- serviceability, not
    # the fee engine, decides whether a distance is deliverable at all.
    "beyond_bands_minor": 100_000,  # ₦1,000.00
    "weight_threshold_grams": 10_000,
    "weight_per_kg_minor": 5_000,  # ₦50.00 per kg over the threshold
}


class ZoneBandStrategy:
    """Base fee per lane, plus a distance band, plus a weight surcharge.

    The distance comes from the shared Haversine in app/libs/geo.py. It is a
    straight line and therefore always shorter than the road -- honest as an
    *estimate*, which is what this is, and consistently wrong in the direction
    that under-quotes rather than over-quotes. Replacing it with real routing
    distance is a change to the caller that builds the context, not to this.
    """

    name = "zone_band"
    version = "1.0.0"

    def __init__(self, config: Optional[dict] = None):
        self.config = {**DEFAULT_FEE_CONFIG, **(config or {})}

    def quote(self, ctx: QuoteContext) -> FeeBreakdown:
        lines: List[FeeLine] = []

        base = (
            ctx.lane_base_fee_minor
            if ctx.lane_base_fee_minor is not None
            else int(self.config["lane_base_minor"])
        )
        lines.append(FeeLine("Base delivery fee", base))

        surcharge = self._distance_surcharge(ctx.distance_km)
        if surcharge:
            lines.append(FeeLine(f"Distance ({ctx.distance_km:.1f} km)", surcharge))

        weight = self._weight_surcharge(ctx.total_weight_grams)
        if weight:
            lines.append(FeeLine("Heavy items", weight))

        return FeeBreakdown(
            total_minor=sum(line.amount_minor for line in lines), lines=lines
        )

    def _distance_surcharge(self, distance_km: float) -> int:
        for lo, hi, amount in self.config["distance_bands"]:
            if lo <= distance_km < hi:
                return int(amount)
        return int(self.config["beyond_bands_minor"])

    def _weight_surcharge(self, grams: int) -> int:
        threshold = int(self.config["weight_threshold_grams"])
        if grams <= threshold:
            return 0
        # Rounded up per kg: a 100g overage still costs a kilo, which is how
        # couriers actually price and avoids a fee that changes by one kobo.
        over_kg = -(-(grams - threshold) // 1000)
        return over_kg * int(self.config["weight_per_kg_minor"])


_REGISTRY = {ZoneBandStrategy.name: ZoneBandStrategy}
_ACTIVE_STRATEGY = ZoneBandStrategy.name


def get_strategy(name: Optional[str] = None) -> FeeStrategy:
    """The strategy in force, or a named one for replaying an old quote.

    Replay matters: an order stores the strategy and version that priced it, so
    a fee from six months ago can still be explained after the engine behind it
    has been replaced.
    """
    key = name or _ACTIVE_STRATEGY
    impl = _REGISTRY.get(key)
    if impl is None:
        logger.warning(
            "Unknown fee strategy %r, falling back to %r", key, _ACTIVE_STRATEGY
        )
        impl = _REGISTRY[_ACTIVE_STRATEGY]
    return impl()


def register_strategy(impl) -> None:
    """For a real landmark/routing strategy to slot in later."""
    _REGISTRY[impl.name] = impl
