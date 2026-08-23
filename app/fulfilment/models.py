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
    # 6.1 ASK gate: the replacement seller has accepted a reroute-created
    # allocation that materially substitutes the buyer's original choice
    # (different price -- see FulfilmentService.accept's docstring), and
    # the buyer's ASK preference means it can't be committed without their
    # approval. Reservation stays held while this is pending.
    AWAITING_BUYER_APPROVAL = "awaiting_buyer_approval"
    # The buyer rejected an AWAITING_BUYER_APPROVAL substitution. Deliberately
    # distinct from DECLINED: the seller did nothing wrong here (they
    # accepted), so this must NOT count against their Seller Reliability
    # Response Rate (app.fulfilment.reliability._RESOLVED excludes it) --
    # only that this particular substitution wasn't acceptable to the buyer.
    BUYER_REJECTED = "buyer_rejected"
    # 13.4 anti-gaming: a seller backs out AFTER accepting (or even
    # starting prep) -- distinct from DECLINED, which happens before any
    # commitment. This is the "accept-then-cancel" pattern the spec names
    # explicitly; see FulfilmentService.cancel_after_accept and
    # reliability.py's cancellation-penalty component. Still pre-dispatch
    # (10.1: nothing dispatches until fulfilment is locked), so a plain
    # reroute is always possible from here -- there's no rider/pickup
    # complication to unwind.
    CANCELLED_BY_SELLER = "cancelled_by_seller"


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
        FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL,
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
            FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL,
            FulfilmentAllocationStatus.DECLINED,
            FulfilmentAllocationStatus.TIMEOUT,
        ],
        FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL: [
            FulfilmentAllocationStatus.ACCEPTED,
            FulfilmentAllocationStatus.BUYER_REJECTED,
            # 9.1 ASK timeout: straight to UNFULFILLED, not REROUTING --
            # the MVP policy is "do not substitute after an ASK timeout,"
            # so there is deliberately no next-candidate retry from here
            # (contrast BUYER_REJECTED, an explicit "not that one" which
            # DOES retry). See FulfilmentService.expire_stale_buyer_approvals.
            FulfilmentAllocationStatus.UNFULFILLED,
        ],
        FulfilmentAllocationStatus.DECLINED: [FulfilmentAllocationStatus.REROUTING],
        FulfilmentAllocationStatus.TIMEOUT: [FulfilmentAllocationStatus.REROUTING],
        FulfilmentAllocationStatus.BUYER_REJECTED: [
            FulfilmentAllocationStatus.REROUTING
        ],
        FulfilmentAllocationStatus.CANCELLED_BY_SELLER: [
            FulfilmentAllocationStatus.REROUTING
        ],
        FulfilmentAllocationStatus.REROUTING: [
            FulfilmentAllocationStatus.ACCEPTED,
            FulfilmentAllocationStatus.UNFULFILLED,
        ],
        FulfilmentAllocationStatus.ACCEPTED: [
            FulfilmentAllocationStatus.PREPARING,
            FulfilmentAllocationStatus.CANCELLED_BY_SELLER,
        ],
        FulfilmentAllocationStatus.PREPARING: [
            FulfilmentAllocationStatus.CANCELLED_BY_SELLER,
        ],
    }

    id = db.Column(db.Integer, primary_key=True)
    order_item_id = db.Column(
        db.Integer, db.ForeignKey("order_items.id"), nullable=False
    )
    seller_id = db.Column(db.Integer, db.ForeignKey("sellers.id"), nullable=False)
    # The Product this allocation is actually reserved against. Usually
    # OrderItem.product_id (the buyer's original listing) -- but a
    # reroute-created allocation references the REPLACEMENT seller's own
    # Product row, which is a different id (no canonical-product concept
    # links different sellers' listings of "the same" item -- see
    # app.fulfilment.rerouting's module docstring). Nullable only for
    # allocations created before this column existed.
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"), nullable=True)
    # Set for reroute-created allocations, which reserve stock against the
    # replacement seller's product BEFORE the seller has accepted -- if
    # this allocation itself ends up DECLINED/TIMEOUT, that reservation
    # needs to be released (InventoryService.release_reservations), same
    # discipline already applied to payment failures and partial-checkout
    # failures. Nullable: the original checkout-created allocation isn't
    # backed by its own reservation record the same way (see
    # PaymentService.initialize_checkout_payment, which reserves stock
    # before the order/allocation exist at all).
    reservation_id = db.Column(
        db.String(12), db.ForeignKey("inventory_reservations.id"), nullable=True
    )
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(
        db.Enum(FulfilmentAllocationStatus),
        default=FulfilmentAllocationStatus.AWAITING_SELLER,
        nullable=False,
    )
    seller_response_deadline = db.Column(db.DateTime, nullable=False)
    # 9.1: set only when this allocation enters AWAITING_BUYER_APPROVAL
    # (see FulfilmentService.accept's 6.1 ASK gate) -- how long Markt
    # waits for the buyer to approve/reject a material substitution before
    # giving up on it entirely (distinct clock from seller_response_deadline,
    # same "earliest relevant deadline wins" principle as 9's other two).
    buyer_response_deadline = db.Column(db.DateTime, nullable=True)

    order_item = db.relationship("OrderItem")
    seller = db.relationship("Seller")
    product = db.relationship("Product")

    __table_args__ = (
        # "One active fulfilment owner per allocation-quantity" (14.5,
        # moved here from Phase 2 once this model existed to constrain).
        # Partial unique index: only ACTIVE_STATUSES rows are constrained,
        # so history from earlier reroute attempts never collides with a
        # new active allocation for the same item.
        db.Index(
            "uq_fulfilment_allocations_active_owner",
            "order_item_id",
            unique=True,
            # SQLAlchemy's db.Enum(SomeEnum) stores each Postgres enum
            # value as the Python member's NAME (e.g. "AWAITING_SELLER"),
            # not its .value, unless values_callable overrides that --
            # this codebase never does. Built from ACTIVE_STATUSES'
            # .name rather than hand-typed lowercase literals so this
            # can't drift out of sync with the real enum type again (an
            # earlier hardcoded-lowercase version of this WHERE clause
            # made db.create_all() fail outright against a real Postgres
            # DB -- caught by the CI job's disposable-database tests,
            # never in local mocked-session tests, since those never
            # touch a real enum type at all).
            postgresql_where=db.text(
                "status IN ({})".format(
                    ", ".join(f"'{s.name}'" for s in ACTIVE_STATUSES)
                )
            ),
        ),
    )

    def transition_to(self, new_status: "FulfilmentAllocationStatus") -> None:
        """Apply a status change, raising ValueError if it isn't a legal transition."""
        allowed = FulfilmentAllocation.VALID_STATUS_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(f"Cannot transition from {self.status} to {new_status}")
        self.status = new_status


class SellerReliabilityScore(BaseModel):
    """Last computed Seller Reliability score (13.2), separate from
    Inventory Confidence (8.3, per-product). Recomputed on a schedule,
    versioned so a future change to the weights/formula doesn't corrupt
    the meaning of historical scores already referenced elsewhere."""

    __tablename__ = "seller_reliability_scores"

    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(
        db.Integer, db.ForeignKey("sellers.id"), nullable=False, unique=True
    )
    score = db.Column(db.Float, nullable=False)
    acceptance_rate_component = db.Column(db.Float, nullable=False)
    response_rate_component = db.Column(db.Float, nullable=False)
    fulfilment_rate_component = db.Column(db.Float, nullable=False)
    inventory_accuracy_component = db.Column(db.Float, nullable=False)
    response_time_component = db.Column(db.Float, nullable=False)
    # 13.4 anti-gaming layer, applied ON TOP of the 13.2 weighted formula
    # above (that formula's five weights are spec-mandated and untouched;
    # this is a separate multiplicative penalty -- see reliability.py's
    # module docstring). Fraction of the seller's accepted allocations in
    # the lookback window that were CANCELLED_BY_SELLER (accept-then-cancel).
    cancellation_penalty = db.Column(db.Float, nullable=False, default=0.0)
    # Crossed a 13.4 anti-gaming threshold (chronic accept-then-cancel
    # and/or suspiciously last-second responses -- see
    # reliability.py's GAMING_FLAG_* constants). Mirrors
    # MarketVerificationStatus.FLAGGED's pattern: a flagged seller is
    # excluded from automated rerouting candidate lookup
    # (app.fulfilment.rerouting.find_candidate_products) until an admin
    # clears it -- "advanced detection" is explicitly deferred by the spec,
    # this is the MVP mitigation, not an auto-ban.
    gaming_flagged = db.Column(db.Boolean, nullable=False, default=False)
    score_version = db.Column(db.Integer, nullable=False, default=1)
    calculated_at = db.Column(db.DateTime, nullable=False)

    seller = db.relationship("Seller")
