from enum import Enum

from external.database import db
from app.libs.models import BaseModel, StatusMixin
from app.libs.helpers import UniqueIdMixin


class InventoryReservation(BaseModel, StatusMixin, UniqueIdMixin):
    __tablename__ = "inventory_reservations"
    id_prefix = "RSV_"

    class Status(Enum):
        REQUESTED = "requested"
        HELD = "held"
        CONFIRMED = "confirmed"
        CONSUMED = "consumed"
        EXPIRED = "expired"
        RELEASED = "released"

    # Single source of truth for legal status transitions, same transition_to
    # pattern as OrderItem/Payment (§8.1). RELEASED covers an explicit
    # release (buyer abandons checkout, seller can't confirm) distinct from
    # EXPIRED (TTL lapsed with no action taken).
    VALID_STATUS_TRANSITIONS = {
        Status.REQUESTED: [Status.HELD, Status.EXPIRED, Status.RELEASED],
        Status.HELD: [Status.CONFIRMED, Status.EXPIRED, Status.RELEASED],
        Status.CONFIRMED: [Status.CONSUMED, Status.RELEASED],
    }

    id = db.Column(db.String(12), primary_key=True, default=None)
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"), nullable=False)
    variant_id = db.Column(
        db.Integer, db.ForeignKey("product_variants.id"), nullable=True
    )
    buyer_id = db.Column(db.Integer, db.ForeignKey("buyers.id"), nullable=False)
    order_id = db.Column(db.String(12), db.ForeignKey("orders.id"), nullable=True)
    quantity = db.Column(db.Integer, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)

    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")
    buyer = db.relationship("Buyer")
    order = db.relationship("Order")

    def transition_to(self, new_status: "InventoryReservation.Status") -> None:
        """Apply a status change, raising ValueError if it isn't a legal transition."""
        allowed = InventoryReservation.VALID_STATUS_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(f"Cannot transition from {self.status} to {new_status}")
        self.status = new_status
