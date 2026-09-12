from datetime import datetime

from external.database import db
from app.libs.models import BaseModel


class BrowseLocation(BaseModel):
    """Where someone is *looking*, which is not where they want things sent.

    Deliberately separate from ShippingAddress. Chowdeck lets you change the
    area you are browsing without touching your saved address, and conflating
    the two means "show me what's in Lagos" silently redirects a delivery to
    Lagos. They answer different questions:

        browse location   what you see        neighbourhood precision
        shipping address  where it goes       exact, with a landmark

    Keyed by user id *or* a guest device id, never both, so a guest can pick an
    area before creating an account and keep it afterwards. That is the whole
    reason guests can browse at all.
    """

    __tablename__ = "browse_locations"

    id = db.Column(db.Integer, primary_key=True)

    # Exactly one of these is set. A guest has no user_id; a signed-in user's
    # row is keyed by user_id so it follows them across devices.
    user_id = db.Column(
        db.String(12), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    guest_id = db.Column(db.String(64), nullable=True)

    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)

    # What to show in the header chip. Denormalised on purpose: re-geocoding on
    # every feed request to render a label would be absurd.
    label = db.Column(db.String(160), nullable=True)
    state = db.Column(db.String(80), nullable=True)
    lga = db.Column(db.String(80), nullable=True)

    updated_at_utc = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", name="uq_browse_location_user"),
        db.UniqueConstraint("guest_id", name="uq_browse_location_guest"),
        db.Index("ix_browse_locations_guest_id", "guest_id"),
    )
