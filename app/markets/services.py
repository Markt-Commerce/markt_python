"""Market/Area assignment and the geocode-distance sanity check on a
seller's claimed Market (§7.2, Phase 6's cross-cutting blocker).

A seller explicitly picks their Market (like Category) -- this module
never infers membership from coordinates. What it does do is check the
claim: geocode the seller's shop address and compare it against the
Market's own reference location. Within tolerance -> VERIFIED. Outside it
-> FLAGGED, and a FLAGGED seller is excluded from rerouting's "same
market" candidate lookup until an admin clears it (enforced by
market_verification_status == VERIFIED in the eligibility filter).

This is a triage signal, not a hard truth: free geocoding of informal
market-stall addresses in Nigeria is often imprecise, so the tolerance is
generous and a FLAGGED result routes to human review rather than
auto-rejection.
"""

from typing import Any, Dict, Optional

from app.libs.errors import NotFoundError, ValidationError
from app.libs.session import session_scope
from app.orders.shipping import geocode_address
from app.users.models import MarketVerificationStatus, Seller

from .models import Market

# Generous on purpose -- see module docstring on geocoding accuracy for
# informal market addresses.
MARKET_VERIFICATION_TOLERANCE_METERS = 2000


class MarketService:
    @staticmethod
    def assign_seller_market(
        seller_id: int, market_id: int, shop_address: Dict[str, Any]
    ) -> Seller:
        """Assign a seller to a Market and sanity-check the claim against
        their geocoded shop address."""
        from app.deliveries.services import DeliveryService

        with session_scope() as session:
            seller = session.query(Seller).get(seller_id)
            if not seller:
                raise NotFoundError("Seller not found")

            market = session.query(Market).get(market_id)
            if not market:
                raise NotFoundError("Market not found")

            lat, lng = geocode_address(shop_address)

            seller.market_id = market_id
            seller.shop_address = shop_address
            seller.shop_latitude = lat
            seller.shop_longitude = lng

            if market.latitude is None or market.longitude is None:
                # Nothing to check the claim against yet -- needs an
                # admin to set the market's own reference location too.
                seller.market_verification_status = MarketVerificationStatus.UNVERIFIED
            else:
                distance = DeliveryService.haversine_distance(
                    lat, lng, market.latitude, market.longitude
                )
                seller.market_verification_status = (
                    MarketVerificationStatus.VERIFIED
                    if distance <= MARKET_VERIFICATION_TOLERANCE_METERS
                    else MarketVerificationStatus.FLAGGED
                )

            session.flush()
            return seller

    @staticmethod
    def seed_market(
        name: str,
        slug: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> Market:
        if latitude is not None and not -90 <= latitude <= 90:
            raise ValidationError(f"Invalid latitude: {latitude}")
        if longitude is not None and not -180 <= longitude <= 180:
            raise ValidationError(f"Invalid longitude: {longitude}")

        with session_scope() as session:
            existing = session.query(Market).filter_by(slug=slug).first()
            if existing:
                return existing

            market = Market(
                name=name, slug=slug, latitude=latitude, longitude=longitude
            )
            session.add(market)
            session.flush()
            return market
