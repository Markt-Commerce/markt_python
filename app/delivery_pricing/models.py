"""Serviceability and quoting.

Sits above the existing Market/Area pair rather than replacing it. Market and
Area are membership concepts -- a seller is assigned to a market the same way
they are assigned to a category, and "geographic coordinates are never the
membership mechanism" (app/markets/models.py). That decision stands.

What was missing is the layer that answers "can we deliver this, and for how
much" before a buyer pays. See docs/ADR-001-delivery-quoting.md.
"""

from datetime import datetime, timedelta
from enum import Enum

from external.database import db
from app.libs.models import BaseModel
from app.libs.helpers import UniqueIdMixin


class ServiceCity(BaseModel):
    """A city Markt has launched delivery in.

    Launch is city-by-city, so this is the outermost gate: no city, no
    delivery, however close two points happen to be.
    """

    __tablename__ = "service_cities"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    slug = db.Column(db.String(110), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    launched_at = db.Column(db.DateTime, nullable=True)

    zones = db.relationship("ServiceZone", back_populates="city")


class ServiceZone(BaseModel):
    """A coarse region within a city.

    `centroid_lat/lng` + `radius_km` is a deliberately crude containment test,
    and is documented as replaceable. Nigerian addressing does not give us
    polygons, and inventing precision we do not have would make the fee look
    authoritative when it is an estimate. When landmark data arrives this
    becomes a lookup table and the containment method changes behind
    `ServiceabilityService.zone_for_point` without touching a caller.
    """

    __tablename__ = "service_zones"

    id = db.Column(db.Integer, primary_key=True)
    city_id = db.Column(db.Integer, db.ForeignKey("service_cities.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(110), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    centroid_lat = db.Column(db.Float, nullable=False)
    centroid_lng = db.Column(db.Float, nullable=False)
    radius_km = db.Column(db.Float, nullable=False)

    city = db.relationship("ServiceCity", back_populates="zones")

    __table_args__ = (db.Index("ix_service_zones_city_active", "city_id", "is_active"),)


class DeliveryLane(BaseModel):
    """A route we actually serve, pickup zone -> dropoff zone.

    A lane rather than a pair of points, because "we deliver from Bodija to UI
    campus" is a decision somebody makes about rider supply and road access. It
    is not derivable from a distance, and quoting a fee for a route no rider
    will take is worse than saying no.

    Same-zone delivery needs a lane where from == to. That is deliberate: it
    keeps "we serve this" a single explicit statement with nothing implied.
    """

    __tablename__ = "delivery_lanes"

    id = db.Column(db.Integer, primary_key=True)
    from_zone_id = db.Column(
        db.Integer, db.ForeignKey("service_zones.id"), nullable=False
    )
    to_zone_id = db.Column(
        db.Integer, db.ForeignKey("service_zones.id"), nullable=False
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Overrides the configured default for this lane only. Null means "use the
    # config", so a lane that is simply expensive can be priced without
    # forking the strategy.
    base_fee_minor_override = db.Column(db.Integer, nullable=True)

    from_zone = db.relationship("ServiceZone", foreign_keys=[from_zone_id])
    to_zone = db.relationship("ServiceZone", foreign_keys=[to_zone_id])

    __table_args__ = (
        db.UniqueConstraint("from_zone_id", "to_zone_id", name="uq_lane_from_to"),
        db.Index("ix_delivery_lanes_active", "is_active"),
    )


class QuoteStatus(Enum):
    ACTIVE = "active"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class DeliveryQuote(BaseModel, UniqueIdMixin):
    """A price for one pickup -> dropoff, valid for a short time.

    Money here is an integer of kobo, never a float. The rest of the codebase
    uses a Numeric MONEY type for stored amounts, which is correct for ledger
    balances; a quote is arithmetic that gets divided by a participant count in
    batch, and integer minor units are the only way that division is
    auditable to the kobo.

    `strategy` and `strategy_version` are stored so a fee stays explainable
    after the engine behind it has changed. Without them, a support question
    about a six-month-old order has no answer.
    """

    __tablename__ = "delivery_quotes"
    id_prefix = "DQT_"

    # Long enough to finish a checkout, short enough that nobody holds a price
    # across a rate change.
    TTL_MINUTES = 15

    id = db.Column(db.String(12), primary_key=True, default=None)
    buyer_id = db.Column(db.Integer, db.ForeignKey("buyers.id"), nullable=False)

    seller_id = db.Column(db.Integer, db.ForeignKey("sellers.id"), nullable=True)
    pickup_zone_id = db.Column(
        db.Integer, db.ForeignKey("service_zones.id"), nullable=False
    )
    dropoff_zone_id = db.Column(
        db.Integer, db.ForeignKey("service_zones.id"), nullable=False
    )

    pickup_lat = db.Column(db.Float, nullable=False)
    pickup_lng = db.Column(db.Float, nullable=False)
    dropoff_lat = db.Column(db.Float, nullable=False)
    dropoff_lng = db.Column(db.Float, nullable=False)
    distance_km = db.Column(db.Float, nullable=False)

    strategy = db.Column(db.String(50), nullable=False)
    strategy_version = db.Column(db.String(20), nullable=False)

    fee_minor = db.Column(db.Integer, nullable=False)
    breakdown = db.Column(db.JSON, nullable=False)

    # "approximate" whenever the dropoff came from a landmark or a
    # reverse-geocode rather than a pin the buyer confirmed. The client uses
    # this to require pin confirmation before payment.
    precision = db.Column(db.String(20), nullable=False, default="approximate")

    status = db.Column(db.Enum(QuoteStatus), default=QuoteStatus.ACTIVE, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    consumed_at = db.Column(db.DateTime, nullable=True)
    order_id = db.Column(db.String(12), db.ForeignKey("orders.id"), nullable=True)

    __table_args__ = (
        db.Index("ix_delivery_quotes_buyer_status", "buyer_id", "status"),
    )

    @staticmethod
    def default_expiry() -> datetime:
        return datetime.utcnow() + timedelta(minutes=DeliveryQuote.TTL_MINUTES)

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at

    @property
    def is_usable(self) -> bool:
        """Active and still in date. Checked again under a row lock at the
        moment of consumption -- this property is for reads, not for deciding
        whether it is safe to charge."""
        return self.status == QuoteStatus.ACTIVE and not self.is_expired
