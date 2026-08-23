"""Market/Area assignment and the geocode-distance sanity check on a
seller's claimed Market (7.2, Phase 6's cross-cutting blocker).

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

from .models import Area, Market

# Generous on purpose -- see module docstring on geocoding accuracy for
# informal market addresses.
MARKET_VERIFICATION_TOLERANCE_METERS = 2000

# 10.1: how close a shipping address's geocoded coordinates must be to an
# Area's own reference location to resolve to it. Areas are a small,
# curated set (initially 3 campuses) rather than a fine-grained geofence,
# so this is deliberately generous -- same reasoning as the market
# verification tolerance above, and the same "explicit assignment,
# geocode is only ever a best-effort/verification signal" philosophy
# (see this module's own docstring): nothing here lets a buyer claim an
# Area, it only auto-resolves one from where their address actually is.
AREA_RESOLUTION_TOLERANCE_METERS = 5000


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
    def resolve_area_for_coordinates(
        session, latitude: Optional[float], longitude: Optional[float]
    ) -> Optional[Area]:
        """10.1: best-effort resolve a shipping address's coordinates to
        the nearest active Area with a reference location, within
        AREA_RESOLUTION_TOLERANCE_METERS. Returns None (never raises) if
        the coordinates are missing, no Area has a reference location
        yet, or nothing is close enough -- an unresolved address simply
        isn't eligible to join a DeliveryRun yet (see ShippingAddress.area_id's
        own docstring), not an error."""
        from app.deliveries.services import DeliveryService

        if latitude is None or longitude is None:
            return None

        areas = (
            session.query(Area)
            .filter(
                Area.is_active.is_(True),
                Area.latitude.isnot(None),
                Area.longitude.isnot(None),
            )
            .all()
        )

        nearest = None
        nearest_distance = None
        for area in areas:
            distance = DeliveryService.haversine_distance(
                latitude, longitude, area.latitude, area.longitude
            )
            if nearest_distance is None or distance < nearest_distance:
                nearest, nearest_distance = area, distance

        if nearest is not None and nearest_distance <= AREA_RESOLUTION_TOLERANCE_METERS:
            return nearest
        return None

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
