from enum import Enum

from external.database import db
from app.libs.models import BaseModel


class FulfilmentAllocationStatus(Enum):
    AWAITING_SELLER = "awaiting_seller"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    TIMEOUT = "timeout"
    REROUTING = "rerouting"
    PREPARING = "preparing"
    UNFULFILLED = "unfulfilled"


class FulfilmentAllocation(BaseModel):
    """Tracks which seller currently owns fulfilment of an OrderItem, and
    that seller's accept/decline/timeout negotiation (12.1-12.2).

    Distinct from OrderItem.status: OrderItem tracks the buyer-facing item
    lifecycle (PENDING/PROCESSING/SHIPPED/DELIVERED/CANCELLED, built in
    Phase 1); this tracks the seller-facing "will you fulfil it"
    negotiation, which can span multiple sellers over time once rerouting
    exists (Phase 6). Only one allocation per order item is ever "active"
    (non-terminal) at once -- enforced by the partial unique index below --
    but DECLINED/TIMEOUT/UNFULFILLED rows accumulate as history across
    reroute attempts.
    """

    __tablename__ = "fulfilment_allocations"

    # Allocations that still represent live ownership/negotiation for an
    # item. Used to enforce "one active owner per item" (see __table_args__).
    ACTIVE_STATUSES = (
        FulfilmentAllocationStatus.AWAITING_SELLER,
        FulfilmentAllocationStatus.ACCEPTED,
        FulfilmentAllocationStatus.PREPARING,
    )

    # Single source of truth for legal transitions, same transition_to
    # pattern as OrderItem/Payment/InventoryReservation. REROUTING is
    # currently a dead end in practice: there's no rerouting engine yet
    # (Phase 6) to move it on to ACCEPTED (a replacement seller) or
    # UNFULFILLED, so a declined/timed-out allocation just sits at
    # REROUTING until Phase 6 exists to resolve it. That's intentional --
    # an honest stuck state, not a fabricated resolution.
    VALID_STATUS_TRANSITIONS = {
        FulfilmentAllocationStatus.AWAITING_SELLER: [
            FulfilmentAllocationStatus.ACCEPTED,
            FulfilmentAllocationStatus.DECLINED,
            FulfilmentAllocationStatus.TIMEOUT,
        ],
        FulfilmentAllocationStatus.DECLINED: [FulfilmentAllocationStatus.REROUTING],
        FulfilmentAllocationStatus.TIMEOUT: [FulfilmentAllocationStatus.REROUTING],
        FulfilmentAllocationStatus.REROUTING: [
            FulfilmentAllocationStatus.ACCEPTED,
            FulfilmentAllocationStatus.UNFULFILLED,
        ],
        FulfilmentAllocationStatus.ACCEPTED: [FulfilmentAllocationStatus.PREPARING],
    }

    id = db.Column(db.Integer, primary_key=True)
    order_item_id = db.Column(
        db.Integer, db.ForeignKey("order_items.id"), nullable=False
    )
    seller_id = db.Column(db.Integer, db.ForeignKey("sellers.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(
        db.Enum(FulfilmentAllocationStatus),
        default=FulfilmentAllocationStatus.AWAITING_SELLER,
        nullable=False,
    )
    seller_response_deadline = db.Column(db.DateTime, nullable=False)

    order_item = db.relationship("OrderItem")
    seller = db.relationship("Seller")

    __table_args__ = (
        # "One active fulfilment owner per allocation-quantity" (§14.5,
        # moved here from Phase 2 once this model existed to constrain).
        # Partial unique index: only ACTIVE_STATUSES rows are constrained,
        # so history from earlier reroute attempts never collides with a
        # new active allocation for the same item.
        db.Index(
            "uq_fulfilment_allocations_active_owner",
            "order_item_id",
            unique=True,
            postgresql_where=db.text(
                "status IN ('awaiting_seller', 'accepted', 'preparing')"
            ),
        ),
    )

    def transition_to(self, new_status: "FulfilmentAllocationStatus") -> None:
        """Apply a status change, raising ValueError if it isn't a legal transition."""
        allowed = FulfilmentAllocation.VALID_STATUS_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(f"Cannot transition from {self.status} to {new_status}")
        self.status = new_status
