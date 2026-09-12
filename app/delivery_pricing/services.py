"""Serviceability checks and quote issue/consumption."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from app.libs.errors import APIError, ConflictError, NotFoundError, ValidationError
from app.libs.geo import haversine_km, is_valid_coordinate
from app.libs.session import session_scope
from external.redis import redis_client

from .fees import QuoteContext, get_strategy
from .models import (
    DeliveryLane,
    DeliveryQuote,
    QuoteStatus,
    ServiceCity,
    ServiceZone,
)

logger = logging.getLogger(__name__)

#: One hour. Long enough that the constant re-asking costs nothing,
#: short enough that switching a city on does not need a cache flush.
SERVICEABILITY_CACHE_TTL = 3600


class NotServiceable(APIError):
    """Delivery is not possible for this pair of points.

    Carries a machine-readable reason so the client can say *which* end is the
    problem. "Delivery unavailable" with no subject is the kind of message that
    makes someone re-enter a perfectly good address five times.
    """

    def __init__(self, reason: str, message: str, payload: Optional[dict] = None):
        # Kept on the exception as well as in the payload. Callers that catch
        # this in Python -- combined quoting, for one -- were reaching for
        # `exc.reason` and silently getting a generic fallback, turning "we
        # don't deliver between these two areas" into "not serviceable".
        self.reason = reason
        super().__init__(
            message,
            422,
            {"error_type": "not_serviceable", "reason": reason, **(payload or {})},
        )


class QuoteExpired(ConflictError):
    def __init__(self, message="This delivery quote has expired."):
        super().__init__(message)
        self.payload = {"error_type": "quote_expired"}


@dataclass(frozen=True)
class Serviceability:
    pickup_zone: ServiceZone
    dropoff_zone: ServiceZone
    lane: DeliveryLane
    distance_km: float


class ServiceabilityService:
    """Whether we deliver between two points, and at what base rate."""

    @staticmethod
    def serviceable_summary(session, lat: float, lng: float) -> dict:
        """Cached answer to "do we deliver here at all".

        Cached because it is the one delivery call that runs constantly and
        answers the same thing every time: the app asks on every address
        change and every cart view, while the served-area map changes a few
        times a year. Without this, every keystroke-adjacent address change
        is a full table scan of every active zone.

        Keyed on coordinates rounded to 4 decimal places -- about 11 metres,
        far finer than a zone boundary, so two lookups that round together
        genuinely have the same answer. Rounding is also what makes the cache
        useful at all: raw GPS never repeats.

        Deliberately short-lived anyway. Switching a city on should take
        effect within the hour without anyone flushing anything, and a stale
        "we don't deliver here" is the expensive kind of wrong.
        """
        key = f"delivery:serviceable:{round(lat, 4)}:{round(lng, 4)}"
        try:
            cached = redis_client.get(key)
            if cached:
                return json.loads(cached)
        except Exception:
            # A cache that cannot be read is not a reason to refuse to
            # answer; fall through to the database.
            logger.debug("Serviceability cache unavailable", exc_info=True)

        zone = ServiceabilityService.zone_for_point(session, lat, lng)
        result = (
            {"serviceable": False, "city": None, "zone": None}
            if zone is None
            else {
                "serviceable": True,
                "city": zone.city.name if zone.city else None,
                "zone": zone.name,
            }
        )
        try:
            redis_client.setex(key, SERVICEABILITY_CACHE_TTL, json.dumps(result))
        except Exception:
            logger.debug("Could not cache serviceability", exc_info=True)
        return result

    @staticmethod
    def zone_for_point(session, lat: float, lng: float) -> Optional[ServiceZone]:
        """The active zone containing a point, or None.

        Nearest-centroid-within-radius. Crude on purpose -- see
        ServiceZone's docstring. Overlapping zones resolve to the nearest
        centroid, which is deterministic and explainable; it is not
        necessarily *right*, and real boundary data replaces it here.
        """
        if not is_valid_coordinate(lat, lng):
            return None

        zones = (
            session.query(ServiceZone)
            .join(ServiceCity, ServiceZone.city_id == ServiceCity.id)
            .filter(ServiceZone.is_active.is_(True), ServiceCity.is_active.is_(True))
            .all()
        )

        best, best_distance = None, None
        for zone in zones:
            d = haversine_km(lat, lng, zone.centroid_lat, zone.centroid_lng)
            if d <= zone.radius_km and (best_distance is None or d < best_distance):
                best, best_distance = zone, d
        return best

    @staticmethod
    def check(
        session,
        pickup: Tuple[float, float],
        dropoff: Tuple[float, float],
    ) -> Serviceability:
        """Raise NotServiceable unless we serve this route, both ends."""
        p_lat, p_lng = pickup
        d_lat, d_lng = dropoff

        if not is_valid_coordinate(p_lat, p_lng):
            raise NotServiceable(
                "pickup_unlocated",
                "This shop hasn't set its location yet, so we can't arrange delivery from it.",
            )
        if not is_valid_coordinate(d_lat, d_lng):
            raise NotServiceable(
                "dropoff_unlocated",
                "We need a delivery address before we can work out a fee.",
            )

        pickup_zone = ServiceabilityService.zone_for_point(session, p_lat, p_lng)
        if pickup_zone is None:
            raise NotServiceable(
                "pickup_not_serviceable",
                "We don't deliver from this shop's area yet.",
            )

        dropoff_zone = ServiceabilityService.zone_for_point(session, d_lat, d_lng)
        if dropoff_zone is None:
            raise NotServiceable(
                "dropoff_not_serviceable",
                "We don't deliver to this address yet.",
                {"city_known": False},
            )

        lane = (
            session.query(DeliveryLane)
            .filter(
                DeliveryLane.from_zone_id == pickup_zone.id,
                DeliveryLane.to_zone_id == dropoff_zone.id,
                DeliveryLane.is_active.is_(True),
            )
            .first()
        )
        if lane is None:
            raise NotServiceable(
                "no_lane",
                "We don't deliver between these two areas yet.",
                {
                    "pickup_zone": pickup_zone.name,
                    "dropoff_zone": dropoff_zone.name,
                },
            )

        return Serviceability(
            pickup_zone=pickup_zone,
            dropoff_zone=dropoff_zone,
            lane=lane,
            distance_km=haversine_km(p_lat, p_lng, d_lat, d_lng),
        )


class QuoteService:
    @staticmethod
    def price_only(
        session,
        pickup: Tuple[float, float],
        dropoff: Tuple[float, float],
        *,
        item_count: int = 1,
        total_weight_grams: int = 0,
    ) -> int:
        """What one leg would cost, without storing a quote.

        For comparing options the buyer has not chosen yet -- pricing three
        possible combinations should not leave three unusable quote rows
        behind, and a quote row is a commitment with a fifteen-minute clock
        on it.

        Raises NotServiceable exactly as create() does, so a caller that
        cannot serve one leg finds out the same way.
        """
        check = ServiceabilityService.check(session, pickup, dropoff)
        strategy = get_strategy()
        breakdown = strategy.quote(
            QuoteContext(
                distance_km=check.distance_km,
                pickup_zone_id=check.pickup_zone.id,
                dropoff_zone_id=check.dropoff_zone.id,
                lane_base_fee_minor=check.lane.base_fee_minor_override,
                item_count=item_count,
                total_weight_grams=total_weight_grams,
            )
        )
        return breakdown.total_minor

    @staticmethod
    def create(
        buyer_id: int,
        pickup: Tuple[float, float],
        dropoff: Tuple[float, float],
        *,
        seller_id: Optional[int] = None,
        item_count: int = 1,
        total_weight_grams: int = 0,
        precision: str = "approximate",
    ) -> DeliveryQuote:
        """Price one pickup -> dropoff and store it.

        Raises NotServiceable rather than returning a fee nobody can honour.
        """
        with session_scope() as session:
            check = ServiceabilityService.check(session, pickup, dropoff)

            strategy = get_strategy()
            breakdown = strategy.quote(
                QuoteContext(
                    distance_km=check.distance_km,
                    pickup_zone_id=check.pickup_zone.id,
                    dropoff_zone_id=check.dropoff_zone.id,
                    lane_base_fee_minor=check.lane.base_fee_minor_override,
                    item_count=item_count,
                    total_weight_grams=total_weight_grams,
                )
            )

            quote = DeliveryQuote(
                buyer_id=buyer_id,
                seller_id=seller_id,
                pickup_zone_id=check.pickup_zone.id,
                dropoff_zone_id=check.dropoff_zone.id,
                pickup_lat=pickup[0],
                pickup_lng=pickup[1],
                dropoff_lat=dropoff[0],
                dropoff_lng=dropoff[1],
                distance_km=check.distance_km,
                strategy=strategy.name,
                strategy_version=strategy.version,
                fee_minor=breakdown.total_minor,
                breakdown=breakdown.as_json(),
                precision=precision,
                expires_at=DeliveryQuote.default_expiry(),
            )
            session.add(quote)
            session.flush()

            # Detach before the scope commits. session_scope expires every
            # instance on commit, so a quote read after this call would issue
            # a fresh SELECT -- and outside a request, where there is no live
            # session, that raises DetachedInstanceError instead. Expunging
            # while the attributes are loaded leaves a plain readable object,
            # which is all any caller wants from this.
            session.expunge(quote)
            return quote

    @staticmethod
    def peek(session, quote_id: str, buyer_id: int) -> DeliveryQuote:
        """Read a quote without consuming it.

        For the payment-first checkout, where the buyer pays before any order
        exists. The fee has to be known to charge the right amount, but there
        is nothing yet to attach the quote to -- so this validates and reads,
        and consume() runs later when the order is created.

        Deliberately not a lock: holding a row lock across a call to Paystack
        would pin it for the length of a network round trip to a third party.
        """
        quote = (
            session.query(DeliveryQuote).filter(DeliveryQuote.id == quote_id).first()
        )
        if quote is None or quote.buyer_id != buyer_id:
            raise NotFoundError("Delivery quote not found")
        if quote.status == QuoteStatus.CONSUMED:
            raise ConflictError("This delivery quote has already been used.")
        if quote.is_expired:
            raise QuoteExpired()
        return quote

    @staticmethod
    def consume(
        session,
        quote_id: str,
        buyer_id: int,
        order_id: str,
        *,
        allow_expired: bool = False,
    ) -> DeliveryQuote:
        """Lock a quote to an order, exactly once.

        `allow_expired` is for the one case where refusing an expired quote
        would be the wrong answer: the buyer has already paid. A quote expires
        to stop a stale price being used to *start* a purchase, not to void one
        that has completed. Between paying and the webhook landing, a slow
        gateway can easily outlast the fifteen-minute window -- and taking
        someone's money and then refusing to record what they bought is not a
        defensible way to enforce a TTL. The expiry is logged instead.

        Takes a row lock and re-checks expiry *inside* it. Reading
        `is_usable` and then writing is a race: two checkout submissions a
        few milliseconds apart would both see an active quote and both
        attach it, and the second order would ride on a fee it never
        reserved.
        """
        quote = (
            session.query(DeliveryQuote)
            .filter(DeliveryQuote.id == quote_id)
            .with_for_update()
            .first()
        )
        if quote is None:
            raise NotFoundError("Delivery quote not found")
        if quote.buyer_id != buyer_id:
            # Not "forbidden": telling someone a quote exists but is not
            # theirs is more than they need to know.
            raise NotFoundError("Delivery quote not found")
        if quote.status == QuoteStatus.CONSUMED:
            if quote.order_id == order_id:
                return quote  # idempotent retry of the same checkout
            raise ConflictError("This delivery quote has already been used.")
        if quote.is_expired:
            if not allow_expired:
                quote.status = QuoteStatus.EXPIRED
                raise QuoteExpired()
            logger.warning(
                "Quote %s was consumed %s after expiring, for order %s -- "
                "honouring it because the buyer has already paid",
                quote.id,
                datetime.utcnow() - quote.expires_at,
                order_id,
            )

        quote.status = QuoteStatus.CONSUMED
        quote.consumed_at = datetime.utcnow()
        quote.order_id = order_id
        return quote

    @staticmethod
    def expire_stale() -> int:
        """Housekeeping. Expiry is enforced at consumption, so this only keeps
        the table honest for reads and reporting."""
        with session_scope() as session:
            return (
                session.query(DeliveryQuote)
                .filter(
                    DeliveryQuote.status == QuoteStatus.ACTIVE,
                    DeliveryQuote.expires_at < datetime.utcnow(),
                )
                .update(
                    {DeliveryQuote.status: QuoteStatus.EXPIRED},
                    synchronize_session=False,
                )
            )
