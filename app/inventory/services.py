from datetime import datetime, timedelta
from typing import List, Optional

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
        """available = reported_quantity - active_reserved_quantity (8)."""
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
        """Atomically reserve stock for a buyer (8.2).

        Locks the product/inventory row that owns the reported quantity so
        two concurrent reservations against the same stock can never both
        act on the same "available" figure -- the second call blocks until
        the first's transaction commits, then re-reads with the first
        reservation already counted.

        Confidence-gated securing (8.3): High -> reserve normally (HELD
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

            band = InventoryConfidenceService.get_band_for_product(
                product_id, session=session
            )

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

    @staticmethod
    def release_reservations(reservation_ids: List[str]) -> None:
        """Release reservations that were made but won't be used (e.g. a
        later item in the same checkout attempt failed to reserve). Skips
        anything already past REQUESTED/HELD rather than raising, since
        this runs as best-effort cleanup on a failure path."""
        if not reservation_ids:
            return
        with session_scope() as session:
            reservations = (
                session.query(InventoryReservation)
                .filter(InventoryReservation.id.in_(reservation_ids))
                .all()
            )
            for reservation in reservations:
                if reservation.status in (
                    InventoryReservation.Status.REQUESTED,
                    InventoryReservation.Status.HELD,
                ):
                    reservation.transition_to(InventoryReservation.Status.RELEASED)

    @staticmethod
    def confirm_reservations(
        session, reservation_ids: List[str], order_id: str
    ) -> List[str]:
        """Confirm reservations into a just-created order (8.1: -> CONFIRMED),
        called from within the same transaction that creates the order (see
        PaymentService.complete_checkout_payment). Idempotent: a reservation
        already at CONFIRMED (or further along) is left alone.

        Returns the ids that could NOT be confirmed -- already EXPIRED/
        RELEASED, or missing entirely -- by the time this ran. 14.3's
        payment/escrow reconciliation gap this closes: Payment.FAILED ->
        COMPLETED is deliberately allowed for a late-webhook rescue (see
        Payment's own transition-graph comment), but a rescued payment's
        reservation may have already lapsed and its stock given to someone
        else in the meantime -- the caller MUST NOT treat a returned id's
        item as secured (see complete_checkout_payment's use of this)."""
        if not reservation_ids:
            return []
        reservations = (
            session.query(InventoryReservation)
            .filter(InventoryReservation.id.in_(reservation_ids))
            .all()
        )
        found_ids = set()
        failed_ids = []
        for reservation in reservations:
            found_ids.add(reservation.id)
            if reservation.status == InventoryReservation.Status.REQUESTED:
                reservation.transition_to(InventoryReservation.Status.HELD)
            if reservation.status == InventoryReservation.Status.HELD:
                reservation.transition_to(InventoryReservation.Status.CONFIRMED)
                reservation.order_id = order_id
            elif reservation.status == InventoryReservation.Status.CONFIRMED:
                reservation.order_id = order_id
            else:
                failed_ids.append(reservation.id)

        failed_ids.extend(rid for rid in reservation_ids if rid not in found_ids)
        return failed_ids
