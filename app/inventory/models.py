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
    # Set when the product's confidence band was Medium at reserve time
    # (§8.3: "reserve + verify quickly"). No verification workflow consumes
    # this yet -- it's a data-model placeholder for a Phase 5/6 follow-up.
    needs_verification = db.Column(db.Boolean, default=False, nullable=False)

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


class HandlingClass(Enum):
    STANDARD = "standard"
    FRAGILE = "fragile"
    PERISHABLE = "perishable"
    TEMPERATURE_CONTROLLED = "temperature_controlled"


class ProductHandling(BaseModel):
    """Per-product delivery-handling constraints (§10.5). Only the data
    model is built here -- per Phase 0, max_dwell_minutes is NOT enforced
    in MVP (rerouting keeps a product with its original seller, so
    freshness isn't at risk in practice); the column exists so that
    decision can be revisited later without a schema change."""

    __tablename__ = "product_handling"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.String(12), db.ForeignKey("products.id"), nullable=False, unique=True
    )
    handling_class = db.Column(
        db.Enum(HandlingClass), default=HandlingClass.STANDARD, nullable=False
    )
    max_transit_minutes = db.Column(db.Integer, nullable=True)
    max_dwell_minutes = db.Column(db.Integer, nullable=True)
    temperature_requirement = db.Column(db.String(50), nullable=True)
    fragile = db.Column(db.Boolean, default=False, nullable=False)
    orientation_requirement = db.Column(db.String(50), nullable=True)

    product = db.relationship("Product")


class InventoryConfidenceScore(BaseModel):
    """Last computed Inventory Confidence score per product (§8.3).
    Recomputed on a schedule rather than on every read."""

    __tablename__ = "inventory_confidence_scores"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.String(12), db.ForeignKey("products.id"), nullable=False, unique=True
    )
    score = db.Column(db.Float, nullable=False)
    recency_component = db.Column(db.Float, nullable=False)
    accuracy_component = db.Column(db.Float, nullable=False)
    fulfilment_component = db.Column(db.Float, nullable=False)
    activity_component = db.Column(db.Float, nullable=False)
    calculated_at = db.Column(db.DateTime, nullable=False)

    product = db.relationship("Product")


class CategoryConfidencePrior(BaseModel):
    """Cold-start prior (§8.4): seeds a new product/seller's confidence
    before there's enough observed behaviour to compute a real score.
    Scoped by category only for now -- Market doesn't exist as a model yet
    (that's Phase 9); add a market_id column and re-scope once it does."""

    __tablename__ = "category_confidence_priors"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), nullable=False, unique=True
    )
    prior_score = db.Column(db.Float, nullable=False)

    category = db.relationship("Category")
