"""Market and Area: pulled forward from Phase 9 to unblock Phase 6's
rerouting engine, which is explicitly within-market only (ADR 18.2).

Market = "a defined cluster of many sellers (a digitised physical
market)" -- a real, named place (e.g. "Bodija Market"). Sellers are
assigned to exactly one Market explicitly, the same way they're already
assigned to a Category -- not computed from geofencing.

Area = "a delivery-target region (a campus at launch)" -- also named and
explicitly assigned, not geo-computed. Buyers resolve to an Area; a
DeliveryRun (Phase 9, not built yet) serves one Market -> one Area.

Both keep latitude/longitude for reference and future use (e.g. 13.1's
Distance/Delivery Cost ranking component), but geographic coordinates are
never the membership mechanism -- see app.markets.services for the
geocode-distance *verification* check on a seller's market claim, which
is a sanity check on top of the explicit assignment, not a replacement
for it.
"""

from external.database import db
from app.libs.models import BaseModel


class Market(BaseModel):
    __tablename__ = "markets"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    slug = db.Column(db.String(110), nullable=False, unique=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class Area(BaseModel):
    __tablename__ = "areas"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    slug = db.Column(db.String(110), nullable=False, unique=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
