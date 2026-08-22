"""Rerouting engine (§7.1): candidate-seller lookup, the hard eligibility
filter (§7.2), and the attempt loop that ties them together with ranking
(§13.1) to actually retry a failed item against the next-best seller. Now
that Market/Area exist (feat/market-area-foundation) to scope "same
market" by.

Product matching: there's no canonical-product concept linking different
sellers' listings of the same real-world item -- each seller's `Product`
row is independent, `sku` is unique *globally* (so two sellers can't both
use the same real-world SKU), and `barcode` isn't reliably populated for
informal-market goods. As a practical interim measure: split the original
product's name into keywords, require every keyword to appear in a
candidate's name, and require both to share the same primary category as
a tightening filter. This is a real, deliberately approximate match, not
a canonical join -- it trades some precision for actually finding
plausible matches given today's catalog. A real fix (a shared
canonical-product concept sellers link their listings to) is bigger,
separate catalog work.

Buyer fulfilment preference (§6): SELLER_ONLY is gated here (attempt_reroute
never looks for candidates at all). ASK's material-substitution gate is
NOT here -- it lives in FulfilmentService.accept(), since "material" only
becomes knowable once a specific replacement seller has actually accepted
(their product's price is what's compared against the original). See that
method's docstring, and FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL.

§13.4 anti-gaming: find_candidate_products excludes a seller whose
SellerReliabilityScore.gaming_flagged is set (chronic accept-then-cancel
and/or last-second responses -- see reliability.py), same enforcement
pattern as a market-verification-FLAGGED seller.

§7.4 Buyer Requests tie-in: when attempt_reroute genuinely exhausts the
direct candidate lookup above (deadline/retry limit, no eligible
candidates, or every candidate losing the stock race -- NOT a SELLER_ONLY
buyer's deliberate no-rerouting choice, which never reaches this), it
reuses the existing app.requests rail as a wider, asynchronous net rather
than building a parallel matching path -- see _escalate_unfulfilled_item
and app.requests.services.BuyerRequestService.create_reroute_request.
This is a genuine COMPLEMENT to the ranked-candidate algorithm above, not
a replacement for it: §7.1's numbered steps describe a synchronous
rank-then-contact process that a SellerOffer response can't give you
(offers arrive whenever a seller gets around to it), so the direct lookup
stays the primary mechanism and this only fires once it's given up.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import List, Optional

from app.categories.models import ProductCategory
from app.inventory.confidence import ConfidenceBand, InventoryConfidenceService
from app.libs.errors import ConflictError, NotFoundError
from app.libs.session import session_scope
from app.orders.models import FulfilmentPreference, OrderItem
from app.products.models import Product
from app.users.models import MarketVerificationStatus, Seller

from .models import (
    FulfilmentAllocation,
    FulfilmentAllocationStatus,
    SellerReliabilityScore,
)

# rank_candidates is imported lazily inside attempt_reroute() (below), not
# here -- ranking.py imports PRICE_HEADROOM_RATE from this module at load
# time, so a module-level import here would be circular.

STOPWORDS = {"the", "a", "an", "of", "and", "or", "for", "with", "in", "on", "to"}

# §7.2: "sufficient inventory confidence" -- Low-confidence sellers don't
# qualify as automatic reroute candidates (they'd need seller confirmation
# before stock counts as secured at all -- see InventoryService.reserve_stock).
MIN_CONFIDENCE_BAND = ConfidenceBand.MEDIUM
_CONFIDENCE_BAND_RANK = {
    ConfidenceBand.LOW: 0,
    ConfidenceBand.MEDIUM: 1,
    ConfidenceBand.HIGH: 2,
}

# Phase 0: permitted AUTO price variation before requiring ASK approval.
PRICE_HEADROOM_RATE = 0.05


def _tokenize(name: str) -> List[str]:
    tokens = re.findall(r"[a-z0-9]+", (name or "").lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def find_candidate_products(
    session, original_product: Product, exclude_seller_id: int
) -> List[Product]:
    """§7.1 step 3: candidate sellers in the same market selling
    (approximately) the same product. Returns their `Product` rows.

    Empty results (rather than raising) whenever there isn't enough to
    work with -- no keywords extracted from the name, no primary
    category, or the original seller has no verified market -- since a
    genuinely un-matchable item should fall through to escalation (§7.3),
    not error out.
    """
    keywords = _tokenize(original_product.name)
    if not keywords:
        return []

    primary_category = (
        session.query(ProductCategory)
        .filter_by(product_id=original_product.id, is_primary=True)
        .first()
    )
    if not primary_category:
        return []

    original_seller = session.query(Seller).get(exclude_seller_id)
    if not original_seller or not original_seller.market_id:
        return []

    query = (
        session.query(Product)
        .join(Seller, Product.seller_id == Seller.id)
        .join(ProductCategory, ProductCategory.product_id == Product.id)
        # Outer join: a seller with no SellerReliabilityScore row yet
        # (cold start) must NOT be excluded -- there's nothing to flag them
        # on. `.isnot(True)` compiles to Postgres' native IS NOT TRUE,
        # which treats that NULL as "not flagged" rather than excluding it
        # the way a plain `!= True` would.
        .outerjoin(
            SellerReliabilityScore, SellerReliabilityScore.seller_id == Seller.id
        )
        .filter(
            Product.seller_id != exclude_seller_id,
            Product.status == Product.Status.ACTIVE,
            ProductCategory.category_id == primary_category.category_id,
            Seller.market_id == original_seller.market_id,
            Seller.market_verification_status == MarketVerificationStatus.VERIFIED,
            # §13.4 anti-gaming: a gaming-flagged seller is excluded from
            # automated candidate lookup, same enforcement pattern as a
            # market-verification-FLAGGED seller above.
            SellerReliabilityScore.gaming_flagged.isnot(True),
        )
    )
    for keyword in keywords:
        query = query.filter(Product.name.ilike(f"%{keyword}%"))

    return query.all()


def filter_eligible_candidates(
    session,
    original_product: Product,
    original_price: float,
    exclude_seller_id: int,
    variant_id: Optional[int] = None,
) -> List[Product]:
    """§7.2 hard eligibility filter, applied before ranking -- a high
    score never overrides a failed eligibility check.

    Evaluates: same product/variant (via find_candidate_products, which
    already scopes to the same market), price boundary, inventory
    confidence. Does NOT evaluate "handling-compatible" or "meets the
    delivery cutoff" -- both need DeliveryRun/cutoff scheduling, which
    doesn't exist yet (Phase 9). Skipped structurally rather than faked;
    revisit once that exists.
    """
    candidates = find_candidate_products(session, original_product, exclude_seller_id)

    price_ceiling = original_price * (1 + PRICE_HEADROOM_RATE)
    eligible = []
    for product in candidates:
        if variant_id is not None and not product.variants:
            # Crude variant compatibility: the original item specified a
            # variant, so a candidate with no variants at all can't match
            # it. Real per-option matching needs the same canonical-
            # product link this whole module is working around.
            continue

        if product.price > price_ceiling:
            continue

        band = InventoryConfidenceService.get_band_for_product(product.id)
        if _CONFIDENCE_BAND_RANK[band] < _CONFIDENCE_BAND_RANK[MIN_CONFIDENCE_BAND]:
            continue

        eligible.append(product)

    return eligible


# Phase 0: total time Markt has to resolve an item, from its very first
# allocation attempt -- distinct from SELLER_RESPONSE_TIMEOUT_MINUTES,
# which bounds one seller's response.
FULFILMENT_DEADLINE_MINUTES = 10

# Not spec-mandated (Phase 0 fixed the deadline, not a retry count) --
# a generous safety net so a pathological "every candidate declines
# instantly" case can't loop forever within the deadline window; in
# practice the 10-min deadline is almost always the binding constraint
# given the 3-min per-seller timeout.
MAX_REROUTE_ATTEMPTS = 5

logger = logging.getLogger(__name__)


def _escalate_unfulfilled_item(failed_allocation_id: int) -> None:
    """§7.4: auto-generate a market-scoped BuyerRequest (see
    app.requests.services.BuyerRequestService.create_reroute_request) for
    an item that genuinely exhausted the direct candidate lookup. Called
    from attempt_reroute right before each UNFULFILLED return that
    represents real exhaustion (not the SELLER_ONLY short-circuit, which
    never reaches this).

    Wrapped in try/except and never raises -- an escalation failure must
    not roll back or mask the more important UNFULFILLED state transition
    that already happened. Also a no-op if this item already has an OPEN
    escalation request (avoids piling up duplicates if attempt_reroute
    somehow gets invoked again for an already-escalated failure).
    """
    try:
        from app.requests.models import BuyerRequest, RequestStatus

        with session_scope() as session:
            failed = session.query(FulfilmentAllocation).get(failed_allocation_id)
            if not failed or failed.status != FulfilmentAllocationStatus.UNFULFILLED:
                return

            order_item = session.query(OrderItem).get(failed.order_item_id)
            if not order_item:
                return
            if order_item.fulfilment_preference == FulfilmentPreference.SELLER_ONLY:
                return

            already_escalated = (
                session.query(BuyerRequest)
                .filter_by(order_item_id=order_item.id, status=RequestStatus.OPEN)
                .first()
            )
            if already_escalated:
                return

            original_product = session.query(Product).get(order_item.product_id)
            if not original_product:
                return

            buyer_user_id = (
                order_item.order.buyer.user_id
                if order_item.order and order_item.order.buyer
                else None
            )
            if not buyer_user_id:
                return

            seller = session.query(Seller).get(order_item.seller_id)
            market_id = seller.market_id if seller else None

            primary_category = (
                session.query(ProductCategory)
                .filter_by(product_id=original_product.id, is_primary=True)
                .first()
            )
            category_id = primary_category.category_id if primary_category else None

            order_item_id = order_item.id
            product_name = original_product.name
            quantity = order_item.quantity
            price = order_item.price

        from app.requests.services import BuyerRequestService

        BuyerRequestService.create_reroute_request(
            buyer_user_id=buyer_user_id,
            order_item_id=order_item_id,
            market_id=market_id,
            category_id=category_id,
            product_name=product_name,
            quantity=quantity,
            price=price,
        )
    except Exception:
        logger.exception(
            "Failed to escalate unfulfilled allocation %s to Buyer Requests",
            failed_allocation_id,
        )


class ReroutingService:
    @staticmethod
    def attempt_reroute(failed_allocation_id: int) -> Optional[FulfilmentAllocation]:
        """§7.1 steps 2-9: called when an allocation lands at DECLINED,
        TIMEOUT, BUYER_REJECTED (§6.1's ASK-gate rejection -- see
        FulfilmentService.buyer_reject_reroute), or CANCELLED_BY_SELLER
        (§13.4 anti-gaming "accept-then-cancel" -- see
        FulfilmentService.cancel_after_accept). Finds and ranks eligible
        in-market candidates (excluding every seller already tried for
        this item) and reserves stock against the top-ranked one, retrying
        down the ranked list if a reservation loses a race. Returns the
        new AWAITING_SELLER allocation on success.

        Returns None if the item couldn't be rerouted -- SELLER_ONLY
        preference (§7.1 step 2), fulfilment deadline or retry limit
        reached, or no eligible candidates at all -- after marking the
        failed allocation UNFULFILLED. §7.3's escalation flow (surfacing
        that to the buyer) isn't built yet; this only gets the state
        honestly to where escalation would pick it up.

        A no-op (returns None without raising) if the allocation isn't
        actually at one of those four statuses -- this can be invoked more
        than once for the same failure without double-processing it.
        """
        with session_scope() as session:
            failed = session.query(FulfilmentAllocation).get(failed_allocation_id)
            if not failed:
                raise NotFoundError("Fulfilment allocation not found")

            if failed.status not in (
                FulfilmentAllocationStatus.DECLINED,
                FulfilmentAllocationStatus.TIMEOUT,
                FulfilmentAllocationStatus.BUYER_REJECTED,
                FulfilmentAllocationStatus.CANCELLED_BY_SELLER,
            ):
                return None

            order_item = session.query(OrderItem).get(failed.order_item_id)
            if not order_item:
                return None

            # §7.1 step 2: SELLER_ONLY means no rerouting at all -- skip
            # straight to the same UNFULFILLED end state §7.3's (unbuilt)
            # escalation flow would pick up from, without even looking for
            # candidates.
            if order_item.fulfilment_preference == FulfilmentPreference.SELLER_ONLY:
                failed.transition_to(FulfilmentAllocationStatus.REROUTING)
                failed.transition_to(FulfilmentAllocationStatus.UNFULFILLED)
                session.flush()
                return None

            first_attempt = (
                session.query(FulfilmentAllocation)
                .filter_by(order_item_id=order_item.id)
                .order_by(FulfilmentAllocation.created_at.asc())
                .first()
            )
            deadline_anchor = (
                first_attempt.created_at if first_attempt else failed.created_at
            )
            deadline = deadline_anchor + timedelta(minutes=FULFILMENT_DEADLINE_MINUTES)

            attempt_count = (
                session.query(FulfilmentAllocation)
                .filter_by(order_item_id=order_item.id)
                .count()
            )

            failed.transition_to(FulfilmentAllocationStatus.REROUTING)

            if datetime.utcnow() >= deadline or attempt_count >= MAX_REROUTE_ATTEMPTS:
                failed.transition_to(FulfilmentAllocationStatus.UNFULFILLED)
                session.flush()
                _escalate_unfulfilled_item(failed_allocation_id)
                return None

            original_product = session.query(Product).get(order_item.product_id)
            if not original_product:
                failed.transition_to(FulfilmentAllocationStatus.UNFULFILLED)
                session.flush()
                return None

            tried_seller_ids = {
                row[0]
                for row in session.query(FulfilmentAllocation.seller_id)
                .filter_by(order_item_id=order_item.id)
                .all()
            }

            eligible = filter_eligible_candidates(
                session,
                original_product,
                order_item.price,
                exclude_seller_id=order_item.seller_id,
                variant_id=order_item.variant_id,
            )
            eligible = [p for p in eligible if p.seller_id not in tried_seller_ids]

            if not eligible:
                failed.transition_to(FulfilmentAllocationStatus.UNFULFILLED)
                session.flush()
                _escalate_unfulfilled_item(failed_allocation_id)
                return None

            from .ranking import rank_candidates

            ranked = rank_candidates(eligible, order_item.price, order_item.quantity)
            buyer_id = order_item.order.buyer_id
            quantity = order_item.quantity
            order_item_id = order_item.id

            session.flush()

        # Reservation is its own atomic transaction (row lock) -- see
        # InventoryService.reserve_stock -- so trying candidates in ranked
        # order happens outside the session block above.
        from app.inventory.services import InventoryService
        from .services import FulfilmentService

        for candidate in ranked:
            try:
                reservation = InventoryService.reserve_stock(
                    candidate["product_id"],
                    buyer_id,
                    quantity,
                )
            except ConflictError:
                # Lost a race for this candidate's stock -- try the next.
                continue

            return FulfilmentService.create_allocation(
                order_item_id,
                candidate["seller_id"],
                quantity,
                product_id=candidate["product_id"],
                reservation_id=reservation.id,
            )

        # Every ranked candidate lost the stock race.
        with session_scope() as session:
            failed = session.query(FulfilmentAllocation).get(failed_allocation_id)
            if failed and failed.status == FulfilmentAllocationStatus.REROUTING:
                failed.transition_to(FulfilmentAllocationStatus.UNFULFILLED)

        _escalate_unfulfilled_item(failed_allocation_id)
        return None
