"""Seller Reliability (13.2): a scored, versioned estimate of how
dependably a seller responds to and fulfils allocations -- separate from
Inventory Confidence (8.3, Phase 3), which is about whether a specific
product is actually in stock, not about the seller's own behaviour.

Same "real where possible, honest placeholder where not" treatment as
Phase 3's confidence formula: Inventory Accuracy has no real data source
here either (same root cause -- no reroute/fulfilment-outcome tracking
yet, Phase 6's own reroute loop is the first thing that will start
generating that signal), so it falls back to a neutral prior rather than
a fabricated measurement.

13.4 anti-gaming layer: applied ON TOP of the 13.2 five-weight formula
above, not folded into it -- those weights are spec-mandated as-is.
cancellation_penalty is a multiplicative deduction proportional to how
often the seller's accepted allocations end in CANCELLED_BY_SELLER
(accept-then-cancel -- see FulfilmentService.cancel_after_accept).
gaming_flagged crosses a threshold on that same signal and/or a pattern
of suspiciously last-second responses, and is enforced the same way a
market-verification-FLAGGED seller is: excluded from automated rerouting
candidate lookup (app.fulfilment.rerouting.find_candidate_products) until
an admin clears it. "Advanced detection later" is the spec's own words
for anything beyond this -- these are the MVP mitigations, not a full
fraud-detection system.
"""

from datetime import datetime, timedelta
from typing import Optional

from external.database import db
from app.libs.errors import NotFoundError
from app.libs.session import session_scope
from app.inventory.confidence import DEFAULT_PRIOR
from app.orders.models import OrderItem
from app.users.models import Seller

from .models import (
    FulfilmentAllocation,
    FulfilmentAllocationStatus,
    SellerReliabilityScore,
)
from .services import SELLER_RESPONSE_TIMEOUT_MINUTES

# 13.2 weights.
WEIGHTS = {
    "acceptance": 0.30,
    "response_rate": 0.20,
    "fulfilment": 0.20,
    "inventory_accuracy": 0.15,
    "response_time": 0.15,
}

SCORE_VERSION = 1
LOOKBACK_DAYS = 30

# 13.4: how much of the base score a seller can lose to cancellation --
# multiplicative, so a 100% accept-then-cancel rate would zero the score
# out entirely; a 30% rate costs 15% of it (0.30 * 0.5).
CANCELLATION_PENALTY_WEIGHT = 0.5
# A response landing in the final 15% of the seller's response window
# counts as "last-second" for anti-gaming purposes -- distinct from (and
# coarser than) the continuous response-time decay already in 13.1's
# ranking formula; this is a pattern-flag, not a score input.
LAST_SECOND_WINDOW_RATE = 0.15
# Crossing either of these (with enough samples to mean something --
# MIN_GAMING_SAMPLE_SIZE) sets gaming_flagged.
GAMING_FLAG_CANCELLATION_THRESHOLD = 0.3
GAMING_FLAG_LAST_SECOND_THRESHOLD = 0.5
MIN_GAMING_SAMPLE_SIZE = 5

# Statuses that represent a seller having said "yes" at some point --
# PREPARING is downstream of ACCEPTED, so it counts too.
_ACCEPTED_LIKE = (
    FulfilmentAllocationStatus.ACCEPTED,
    FulfilmentAllocationStatus.PREPARING,
)
_RESOLVED = _ACCEPTED_LIKE + (
    FulfilmentAllocationStatus.DECLINED,
    FulfilmentAllocationStatus.TIMEOUT,
)
# For the cancellation-rate denominator: every allocation that got as far
# as an accept, whether it stayed accepted or was later reneged on.
_ACCEPTED_OR_CANCELLED = _ACCEPTED_LIKE + (
    FulfilmentAllocationStatus.CANCELLED_BY_SELLER,
)
# For the last-second-response check: the same "first response" statuses
# _response_time_component already uses below -- CANCELLED_BY_SELLER is
# deliberately excluded here, since that row's updated_at reflects the
# later cancellation, not the original accept/decline response.
_FIRST_RESPONSE_LIKE = (
    FulfilmentAllocationStatus.ACCEPTED,
    FulfilmentAllocationStatus.PREPARING,
    FulfilmentAllocationStatus.DECLINED,
)


def _response_time_decay(seconds: float) -> float:
    """Full score for a near-instant response, decaying to 0 by the full
    seller-response-timeout window -- same decay shape as Phase 3's
    recency component, just on a minutes-not-days timescale."""
    window_seconds = SELLER_RESPONSE_TIMEOUT_MINUTES * 60
    if seconds <= 0:
        return 1.0
    if seconds >= window_seconds:
        return 0.0
    return round(1.0 - (seconds / window_seconds), 4)


class SellerReliabilityService:
    @staticmethod
    def _status_counts(session, seller_id: int, cutoff: datetime) -> dict:
        rows = (
            session.query(
                FulfilmentAllocation.status, db.func.count(FulfilmentAllocation.id)
            )
            .filter(
                FulfilmentAllocation.seller_id == seller_id,
                FulfilmentAllocation.created_at >= cutoff,
                FulfilmentAllocation.status.in_(_RESOLVED),
            )
            .group_by(FulfilmentAllocation.status)
            .all()
        )
        return dict(rows)

    @staticmethod
    def _acceptance_and_response_rate(
        counts: dict,
    ) -> "tuple[Optional[float], Optional[float]]":
        accepted = sum(counts.get(s, 0) for s in _ACCEPTED_LIKE)
        declined = counts.get(FulfilmentAllocationStatus.DECLINED, 0)
        timed_out = counts.get(FulfilmentAllocationStatus.TIMEOUT, 0)
        resolved = accepted + declined + timed_out
        if resolved == 0:
            return None, None

        acceptance_rate = round(accepted / resolved, 4)
        response_rate = round((accepted + declined) / resolved, 4)
        return acceptance_rate, response_rate

    @staticmethod
    def _fulfilment_rate(session, seller_id: int, cutoff: datetime) -> Optional[float]:
        rows = (
            session.query(OrderItem.status)
            .join(
                FulfilmentAllocation,
                FulfilmentAllocation.order_item_id == OrderItem.id,
            )
            .filter(
                FulfilmentAllocation.seller_id == seller_id,
                FulfilmentAllocation.created_at >= cutoff,
                FulfilmentAllocation.status.in_(_ACCEPTED_LIKE),
            )
            .all()
        )
        if not rows:
            return None

        total = len(rows)
        delivered = sum(1 for (status,) in rows if status == OrderItem.Status.DELIVERED)
        return round(delivered / total, 4)

    @staticmethod
    def _response_time_component(
        session, seller_id: int, cutoff: datetime
    ) -> Optional[float]:
        rows = (
            session.query(
                FulfilmentAllocation.created_at, FulfilmentAllocation.updated_at
            )
            .filter(
                FulfilmentAllocation.seller_id == seller_id,
                FulfilmentAllocation.created_at >= cutoff,
                FulfilmentAllocation.status.in_(_FIRST_RESPONSE_LIKE),
            )
            .all()
        )
        if not rows:
            return None

        scores = [
            _response_time_decay((updated_at - created_at).total_seconds())
            for created_at, updated_at in rows
        ]
        return round(sum(scores) / len(scores), 4)

    @staticmethod
    def _cancellation_stats(
        session, seller_id: int, cutoff: datetime
    ) -> "tuple[float, int]":
        """13.4: (cancellation_rate, sample_size) -- fraction of the
        seller's accepted allocations that were later CANCELLED_BY_SELLER
        rather than left standing. Zero-rate/zero-sample rather than None
        when there's nothing to measure -- unlike the 13.2 components
        above, this isn't itself one of the weighted formula's inputs, so
        there's no neutral-prior fallback to reason about; "no data" and
        "no cancellations" both correctly mean "no penalty."""
        rows = (
            session.query(
                FulfilmentAllocation.status, db.func.count(FulfilmentAllocation.id)
            )
            .filter(
                FulfilmentAllocation.seller_id == seller_id,
                FulfilmentAllocation.created_at >= cutoff,
                FulfilmentAllocation.status.in_(_ACCEPTED_OR_CANCELLED),
            )
            .group_by(FulfilmentAllocation.status)
            .all()
        )
        counts = dict(rows)
        sample_size = sum(counts.get(s, 0) for s in _ACCEPTED_OR_CANCELLED)
        if sample_size == 0:
            return 0.0, 0

        cancelled = counts.get(FulfilmentAllocationStatus.CANCELLED_BY_SELLER, 0)
        return round(cancelled / sample_size, 4), sample_size

    @staticmethod
    def _last_second_response_stats(
        session, seller_id: int, cutoff: datetime
    ) -> "tuple[float, int]":
        """13.4: (last_second_rate, sample_size) -- fraction of the
        seller's first responses that landed in the final
        LAST_SECOND_WINDOW_RATE of their response window. A response with
        a non-positive window (bad data) is skipped, not counted either
        way."""
        rows = (
            session.query(
                FulfilmentAllocation.created_at,
                FulfilmentAllocation.updated_at,
                FulfilmentAllocation.seller_response_deadline,
            )
            .filter(
                FulfilmentAllocation.seller_id == seller_id,
                FulfilmentAllocation.created_at >= cutoff,
                FulfilmentAllocation.status.in_(_FIRST_RESPONSE_LIKE),
            )
            .all()
        )

        sample_size = 0
        last_second = 0
        for created_at, updated_at, deadline in rows:
            window_seconds = (deadline - created_at).total_seconds()
            if window_seconds <= 0:
                continue
            sample_size += 1
            elapsed_seconds = (updated_at - created_at).total_seconds()
            if elapsed_seconds >= window_seconds * (1 - LAST_SECOND_WINDOW_RATE):
                last_second += 1

        if sample_size == 0:
            return 0.0, 0
        return round(last_second / sample_size, 4), sample_size

    @staticmethod
    def calculate_score(seller_id: int) -> SellerReliabilityScore:
        """Recompute and persist the reliability score for one seller."""
        now = datetime.utcnow()
        cutoff = now - timedelta(days=LOOKBACK_DAYS)

        with session_scope() as session:
            seller = session.query(Seller).get(seller_id)
            if not seller:
                raise NotFoundError(f"Seller {seller_id} not found")

            counts = SellerReliabilityService._status_counts(session, seller_id, cutoff)
            (
                acceptance,
                response_rate,
            ) = SellerReliabilityService._acceptance_and_response_rate(counts)
            fulfilment = SellerReliabilityService._fulfilment_rate(
                session, seller_id, cutoff
            )
            response_time = SellerReliabilityService._response_time_component(
                session, seller_id, cutoff
            )
            (
                cancellation_rate,
                cancellation_sample,
            ) = SellerReliabilityService._cancellation_stats(session, seller_id, cutoff)
            (
                last_second_rate,
                last_second_sample,
            ) = SellerReliabilityService._last_second_response_stats(
                session, seller_id, cutoff
            )

            # No real Inventory Accuracy signal exists yet (see module
            # docstring) -- neutral prior, not a fabricated measurement.
            inventory_accuracy = DEFAULT_PRIOR

            # A component with nothing to measure yet falls back to the
            # same neutral prior rather than scoring a quiet seller as 0
            # -- mirrors Phase 3's cold-start treatment.
            acceptance = acceptance if acceptance is not None else DEFAULT_PRIOR
            response_rate = (
                response_rate if response_rate is not None else DEFAULT_PRIOR
            )
            fulfilment = fulfilment if fulfilment is not None else DEFAULT_PRIOR
            response_time = (
                response_time if response_time is not None else DEFAULT_PRIOR
            )

            base_score = (
                WEIGHTS["acceptance"] * acceptance
                + WEIGHTS["response_rate"] * response_rate
                + WEIGHTS["fulfilment"] * fulfilment
                + WEIGHTS["inventory_accuracy"] * inventory_accuracy
                + WEIGHTS["response_time"] * response_time
            )

            # 13.4: multiplicative penalty on top of the 13.2 formula
            # above (that formula's own weights are unchanged).
            cancellation_penalty = round(
                cancellation_rate * CANCELLATION_PENALTY_WEIGHT, 4
            )
            score = round(base_score * (1 - cancellation_penalty), 4)

            gaming_flagged = (
                cancellation_sample >= MIN_GAMING_SAMPLE_SIZE
                and cancellation_rate >= GAMING_FLAG_CANCELLATION_THRESHOLD
            ) or (
                last_second_sample >= MIN_GAMING_SAMPLE_SIZE
                and last_second_rate >= GAMING_FLAG_LAST_SECOND_THRESHOLD
            )

            record = (
                session.query(SellerReliabilityScore)
                .filter_by(seller_id=seller_id)
                .first()
            )
            if record:
                record.score = score
                record.acceptance_rate_component = acceptance
                record.response_rate_component = response_rate
                record.fulfilment_rate_component = fulfilment
                record.inventory_accuracy_component = inventory_accuracy
                record.response_time_component = response_time
                record.cancellation_penalty = cancellation_penalty
                record.gaming_flagged = gaming_flagged
                record.score_version = SCORE_VERSION
                record.calculated_at = now
            else:
                record = SellerReliabilityScore(
                    seller_id=seller_id,
                    score=score,
                    acceptance_rate_component=acceptance,
                    response_rate_component=response_rate,
                    fulfilment_rate_component=fulfilment,
                    inventory_accuracy_component=inventory_accuracy,
                    response_time_component=response_time,
                    cancellation_penalty=cancellation_penalty,
                    gaming_flagged=gaming_flagged,
                    score_version=SCORE_VERSION,
                    calculated_at=now,
                )
                session.add(record)

            session.flush()
            return record

    @staticmethod
    def get_score(seller_id: int) -> float:
        """Last computed score, or the neutral prior if none exists yet."""
        with session_scope() as session:
            record = (
                session.query(SellerReliabilityScore)
                .filter_by(seller_id=seller_id)
                .first()
            )
            return record.score if record else DEFAULT_PRIOR

    @staticmethod
    def get_response_rate(seller_id: int) -> float:
        """Last computed Response Rate component, or the neutral prior --
        reused by the 13.1 ranking scorer's "Response Reliability" input
        rather than recomputed separately, since it's the same signal."""
        with session_scope() as session:
            record = (
                session.query(SellerReliabilityScore)
                .filter_by(seller_id=seller_id)
                .first()
            )
            return record.response_rate_component if record else DEFAULT_PRIOR
