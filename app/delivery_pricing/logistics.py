"""The boundary between Markt and whoever moves the parcel.

Markt already has a rider-facing execution layer -- DeliveryUser, run
assignments, live location, QR proof-of-delivery. The plan is to partner with
a logistics company who will be affiliated with us, which means both need to
work: our own riders in some places, a partner's fleet in others, quite
possibly at the same time in different cities.

So this is an interface with two implementations rather than a rewrite of
either. An adapter takes a paid order and returns a job reference; status flows
back through `apply_status`, whether that arrives from our own rider app or a
partner's webhook. Neither side of that knows which adapter produced the job.

The contract is documented for the partner in docs/LOGISTICS_API_CONTRACT.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol

from decouple import config

from .order_delivery import DeliveryState, OrderDelivery

logger = logging.getLogger(__name__)


class LogisticsError(Exception):
    """Job creation failed. Deliberately not an APIError: the buyer has
    already paid and this is not their problem to solve, so it must never
    become their error message."""


@dataclass(frozen=True)
class DeliveryJob:
    """What an adapter hands back. `reference` is whatever that provider calls
    a job; Markt only stores and echoes it."""

    reference: str
    provider: str
    estimated_pickup_at: Optional[datetime] = None


@dataclass(frozen=True)
class JobRequest:
    """Everything a provider needs, and nothing it does not.

    No buyer identity beyond a contact name and phone: a courier needs to find
    a door and announce themselves, not to know who shops on Markt.
    """

    order_id: str
    pickup_lat: float
    pickup_lng: float
    pickup_contact: str
    dropoff_lat: float
    dropoff_lng: float
    dropoff_contact: str
    dropoff_phone: Optional[str]
    item_count: int
    total_weight_grams: int
    fee_minor: int
    notes: Optional[str] = None


class LogisticsAdapter(Protocol):
    name: str

    def create_job(self, request: JobRequest) -> DeliveryJob:
        ...


class InternalFleetAdapter:
    """Our own riders.

    Creates nothing external: the order becomes eligible for the existing
    DeliveryRun machinery, which is what assigns a rider. The "job reference"
    is the order itself, because there is no other system to reference.
    """

    name = "internal"

    def create_job(self, request: JobRequest) -> DeliveryJob:
        logger.info("Delivery %s queued for the internal fleet", request.order_id)
        return DeliveryJob(reference=request.order_id, provider=self.name)


class PartnerStubAdapter:
    """Stands in for the partner until their API exists.

    Deliberately does *not* pretend to succeed quietly. It returns a reference
    prefixed so nobody mistakes a stubbed job for a real one, and it logs at
    warning level, because a stub that looks like production is how a stub
    reaches production.
    """

    name = "partner_stub"

    def create_job(self, request: JobRequest) -> DeliveryJob:
        logger.warning(
            "PartnerStubAdapter: no real logistics provider configured, "
            "order %s has no actual courier job",
            request.order_id,
        )
        return DeliveryJob(reference=f"STUB-{request.order_id}", provider=self.name)


_ADAPTERS = {
    InternalFleetAdapter.name: InternalFleetAdapter,
    PartnerStubAdapter.name: PartnerStubAdapter,
}


def get_adapter(name: Optional[str] = None) -> LogisticsAdapter:
    key = name or config("LOGISTICS_ADAPTER", default=InternalFleetAdapter.name)
    impl = _ADAPTERS.get(key)
    if impl is None:
        logger.error(
            "Unknown logistics adapter %r; falling back to the internal fleet", key
        )
        impl = InternalFleetAdapter
    return impl()


def register_adapter(impl) -> None:
    """For the partner's real adapter to slot in without touching callers."""
    _ADAPTERS[impl.name] = impl


# --- inbound status ---------------------------------------------------------
# One vocabulary, whoever is reporting. A partner sends their own words; this
# is where they become ours, in one place, so nothing downstream has to know
# which provider a status came from.
PROVIDER_STATUS_MAP = {
    "assigned": DeliveryState.ASSIGNED,
    "accepted": DeliveryState.ASSIGNED,
    "picked_up": DeliveryState.PICKED_UP,
    "collected": DeliveryState.PICKED_UP,
    "in_transit": DeliveryState.IN_TRANSIT,
    "en_route": DeliveryState.IN_TRANSIT,
    "delivered": DeliveryState.DELIVERED,
    "completed": DeliveryState.DELIVERED,
    "failed": DeliveryState.FAILED,
    "cancelled": DeliveryState.CANCELLED,
}


def apply_status(
    delivery: OrderDelivery, provider_status: str, *, reason: Optional[str] = None
) -> bool:
    """Move a delivery on from a provider's report.

    Returns False rather than raising for a status we do not recognise or a
    transition that is not legal. A courier's webhook retrying a status we have
    already passed is normal traffic, not an incident, and 500ing at it just
    makes them retry harder.
    """
    mapped = PROVIDER_STATUS_MAP.get((provider_status or "").strip().lower())
    if mapped is None:
        logger.warning(
            "Unrecognised delivery status %r for %s", provider_status, delivery.order_id
        )
        return False

    if mapped == delivery.state:
        return False  # a duplicate webhook, which is expected

    try:
        delivery.transition_to(mapped)
    except ValueError:
        logger.info(
            "Ignoring out-of-order delivery status %s for %s (currently %s)",
            mapped.value,
            delivery.order_id,
            delivery.state.value,
        )
        return False

    if reason:
        delivery.failure_reason = reason
    return True
