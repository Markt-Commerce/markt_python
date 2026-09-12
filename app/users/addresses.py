"""A buyer's address book.

Markt already had three notions of an address and none of them was this:
`UserAddress` is exactly one row per user and gets overwritten on every save,
`Buyer.shipping_address` is a JSON blob of the same thing, and
`ShippingAddress` is the snapshot taken when an order is placed. None of them
lets someone keep "home", "the shop", and "my sister's place" and pick
between them at checkout.

So: a real address book, many per user, each one a place a courier can
actually find.

The shape is deliberately what a rider needs rather than what a postal system
wants. A coordinate and a landmark get a parcel to a door in Ogbomoso; a
street number and a postcode frequently do not, because plenty of the places
Markt delivers to have neither. That is why `label`, `directions` and
`entry_code` are first-class and `postal_code` is not here at all.
"""

from enum import Enum

from external.database import db
from app.libs.models import BaseModel


class BuildingType(Enum):
    """What the rider is looking for when they arrive."""

    HOUSE = "house"
    APARTMENT = "apartment"
    OFFICE = "office"
    SHOP = "shop"
    HOSTEL = "hostel"
    SCHOOL = "school"
    HOSPITAL = "hospital"
    OTHER = "other"


class SavedAddress(BaseModel):
    __tablename__ = "saved_addresses"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.String(12), db.ForeignKey("users.id"), nullable=False, index=True
    )

    #: What the buyer calls it -- "Home", "Mum's place". Optional: forcing a
    #: name on someone adding a one-off delivery address is friction for no
    #: gain, and the formatted address is a fine fallback.
    label = db.Column(db.String(60), nullable=True)

    #: The line shown in lists, as the geocoder returned it. Stored rather
    #: than re-derived so an address the buyer has used for months does not
    #: silently re-word itself when a geocoder updates.
    formatted_address = db.Column(db.String(500), nullable=False)

    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)

    building_type = db.Column(
        db.Enum(BuildingType), nullable=False, default=BuildingType.HOUSE
    )
    #: Gate code, or whatever gets someone past the door.
    entry_code = db.Column(db.String(40), nullable=True)
    #: "Blue gate opposite the mosque", "second floor". The thing that
    #: actually finds the place.
    directions = db.Column(db.Text, nullable=True)

    #: Who to call on arrival. Defaults to the account holder at the point of
    #: use rather than being required here, because most addresses are your
    #: own and asking twice is noise.
    contact_name = db.Column(db.String(100), nullable=True)
    contact_phone = db.Column(db.String(20), nullable=True)

    #: Exactly one default per user, enforced in the service rather than by a
    #: partial index, so the "promote another one" behaviour on delete lives
    #: in one readable place.
    is_default = db.Column(db.Boolean, nullable=False, default=False)

    #: Bumped whenever an order ships here, so the picker can lead with the
    #: places someone actually uses instead of the order they were typed in.
    last_used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship(
        "User", backref=db.backref("saved_addresses", lazy="dynamic")
    )

    def __repr__(self) -> str:
        return f"<SavedAddress {self.id} {self.label or self.formatted_address[:24]!r}>"

    @property
    def display_label(self) -> str:
        """What to show as the title of a row."""
        return self.label or self.formatted_address
