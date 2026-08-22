from datetime import datetime, timedelta
from typing import Optional

from external.database import db
from app.libs.errors import ConflictError, NotFoundError, ValidationError
from app.libs.session import session_scope
from app.products.models import Product, ProductInventory

from .confidence import ConfidenceBand, InventoryConfidenceService
from .models import InventoryReservation

# Reservations that still hold stock against a product/variant. CONSUMED,
# EXPIRED, and RELEASED reservations no longer tie up inventory, so they're
# excluded from the "active" set used to compute availability.
ACTIVE_RESERVATION_STATUSES = (
    InventoryReservation.Status.REQUESTED,
    InventoryReservation.Status.HELD,
    InventoryReservation.Status.CONFIRMED,
)

# Covers the external Paystack redirect/payment window (Phase 0 decision).
RESERVATION_TTL_MINUTES = 10


class InventoryService:
    @staticmethod
    def get_reported_quantity(
        session, product_id: str, variant_id: Optional[int] = None
    ) -> int:
        """Seller-reported stock, before subtracting active reservations."""
        if variant_id:
            inventory = (
                session.query(ProductInventory)
                .filter_by(product_id=product_id, variant_id=variant_id)
                .first()
            )
            return inventory.quantity if inventory else 0

        product = session.query(Product).get(product_id)
        return product.stock if product else 0

    @staticmethod
    def get_active_reserved_quantity(
        session, product_id: str, variant_id: Optional[int] = None
    ) -> int:
        """Sum of quantity across reservations still holding this product/variant."""
        filters = [
            InventoryReservation.product_id == product_id,
            InventoryReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
        ]
        if variant_id:
            filters.append(InventoryReservation.variant_id == variant_id)
        else:
            filters.append(InventoryReservation.variant_id.is_(None))

        total = (
            session.query(db.func.sum(InventoryReservation.quantity))
            .filter(*filters)
            .scalar()
        )
        return total or 0

    @staticmethod
    def get_available_quantity(
        product_id: str, variant_id: Optional[int] = None
    ) -> int:
        """available = reported_quantity - active_reserved_quantity (§8)."""
        with session_scope() as session:
            reported = InventoryService.get_reported_quantity(
                session, product_id, variant_id
            )
            active_reserved = InventoryService.get_active_reserved_quantity(
                session, product_id, variant_id
            )
            return max(reported - active_reserved, 0)

    @staticmethod
    def reserve_stock(
        product_id: str,
        buyer_id: int,
        quantity: int,
        variant_id: Optional[int] = None,
    ) -> InventoryReservation:
        """Atomically reserve stock for a buyer (§8.2).

        Locks the product/inventory row that owns the reported quantity so
        two concurrent reservations against the same stock can never both
        act on the same "available" figure -- the second call blocks until
        the first's transaction commits, then re-reads with the first
        reservation already counted.

        Confidence-gated securing (§8.3): High -> reserve normally (HELD
        immediately). Medium -> reserve, but flag needs_verification so a
        follow-up check can happen (no verification workflow consumes this
        flag yet). Low -> left at REQUESTED rather than promoted to HELD,
        since Low confidence means stock isn't secured until the seller
        confirms it (no seller-confirmation endpoint exists yet either --
        this only gets the state representation right, not the workflow).
        """
        if quantity <= 0:
            raise ValidationError("Reservation quantity must be positive")

        with session_scope() as session:
            if variant_id:
                owner = (
                    session.query(ProductInventory)
                    .filter_by(product_id=product_id, variant_id=variant_id)
                    .with_for_update()
                    .first()
                )
            else:
                owner = (
                    session.query(Product)
                    .filter_by(id=product_id)
                    .with_for_update()
                    .first()
                )

            if not owner:
                raise NotFoundError("Product not found")

            reported = owner.quantity if variant_id else owner.stock
            active_reserved = InventoryService.get_active_reserved_quantity(
                session, product_id, variant_id
            )
            available = max(reported - active_reserved, 0)

            if quantity > available:
                raise ConflictError(
                    f"Only {available} unit(s) available for product {product_id}"
                )

            band = InventoryConfidenceService.get_band_for_product(product_id)

            reservation = InventoryReservation(
                product_id=product_id,
                variant_id=variant_id,
                buyer_id=buyer_id,
                quantity=quantity,
                status=InventoryReservation.Status.REQUESTED,
                needs_verification=(band == ConfidenceBand.MEDIUM),
                expires_at=datetime.utcnow()
                + timedelta(minutes=RESERVATION_TTL_MINUTES),
            )
            if band != ConfidenceBand.LOW:
                reservation.transition_to(InventoryReservation.Status.HELD)
            session.add(reservation)
            session.flush()
            return reservation
