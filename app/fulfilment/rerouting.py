"""Rerouting engine (7.1): candidate-seller lookup, the hard eligibility
filter (7.2), and the attempt loop that ties them together with ranking
(13.1) to actually retry a failed item against the next-best seller. Now
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

Buyer fulfilment preference (6): SELLER_ONLY is gated here (attempt_reroute
never looks for candidates at all). ASK's material-substitution gate is
NOT here -- it lives in FulfilmentService.accept(), since "material" only
becomes knowable once a specific replacement seller has actually accepted
(their product's price is what's compared against the original). See that
method's docstring, and FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL.

13.4 anti-gaming: find_candidate_products excludes a seller whose
SellerReliabilityScore.gaming_flagged is set (chronic accept-then-cancel
and/or last-second responses -- see reliability.py), same enforcement
pattern as a market-verification-FLAGGED seller.

7.4 Buyer Requests tie-in: when attempt_reroute genuinely exhausts the
direct candidate lookup above (deadline/retry limit, no eligible
candidates, or every candidate losing the stock race -- NOT a SELLER_ONLY
buyer's deliberate no-rerouting choice, which never reaches this), it
reuses the existing app.requests rail as a wider, asynchronous net rather
than building a parallel matching path -- see escalate_unfulfilled_item
and app.requests.services.BuyerRequestService.create_reroute_request.
This is a genuine COMPLEMENT to the ranked-candidate algorithm above, not
a replacement for it: 7.1's numbered steps describe a synchronous
rank-then-contact process that a SellerOffer response can't give you
(offers arrive whenever a seller gets around to it), so the direct lookup
stays the primary mechanism and this only fires once it's given up.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import List, Optional

from external.database import db

from app.categories.models import ProductCategory
from app.inventory.confidence import ConfidenceBand, InventoryConfidenceService
from app.libs.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.libs.session import session_scope
from app.notifications.models import NotificationType
from app.notifications.services import NotificationService
from app.orders.events import ActorType, OrderEventService, OrderEventType
from app.orders.models import FulfilmentPreference, Order, OrderItem
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

# 7.2: "sufficient inventory confidence" -- Low-confidence sellers don't
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


def _notify_buyer_item_unfulfilled(order_item: OrderItem, reason: str) -> None:
    """Phase 12 (15): "no replacement found" notification, fired
    alongside each ITEM_UNFULFILLED event emission in attempt_reroute
    below. Called from inside the caller's still-open session_scope(),
    right after that transaction's own session.flush() -- like
    escalate_unfulfilled_item (this module's other post-flush side
    effect at these exact call sites), NotificationService.create_notification
    opens its own nested session_scope() to persist the Notification row,
    which will commit the caller's transaction early. Unlike
    InventoryService.reserve_stock (where this same pattern silently broke
    a row-locked concurrency guarantee -- see the Phase 11 CI investigation),
    nothing here holds a lock or does anything further in the same
    transaction after this point, so the early commit has no correctness
    consequence -- it just makes the outer session_scope()'s own final
    commit a no-op. Wrapped in try/except: a notification failure must
    never mask the state transition that already happened."""
    try:
        buyer_user_id = (
            order_item.order.buyer.user_id
            if order_item.order and order_item.order.buyer
            else None
        )
        if not buyer_user_id:
            return
        NotificationService.create_notification(
            user_id=buyer_user_id,
            notification_type=NotificationType.ITEM_UNFULFILLED,
            reference_type="order_item",
            reference_id=str(order_item.id),
            metadata_={
                "message": (
                    "We couldn't find a replacement seller for an item in "
                    "your order. Check your order for details."
                ),
                "reason": reason,
            },
        )
    except Exception:
        logger.exception("Failed to notify buyer of unfulfilled item %s", order_item.id)


def find_candidate_products(
    session, original_product: Product, exclude_seller_id: int
) -> List[Product]:
    """7.1 step 3: candidate sellers in the same market selling
    (approximately) the same product. Returns their `Product` rows.

    Empty results (rather than raising) whenever there isn't enough to
    work with -- no keywords extracted from the name, no primary
    category, or the original seller has no verified market -- since a
    genuinely un-matchable item should fall through to escalation (7.3),
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
            # 13.4 anti-gaming: a gaming-flagged seller is excluded from
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
    """7.2 hard eligibility filter, applied before ranking -- a high
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

        band = InventoryConfidenceService.get_band_for_product(
            product.id, session=session
        )
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


def escalate_unfulfilled_item(failed_allocation_id: int) -> None:
    """7.4: auto-generate a market-scoped BuyerRequest (see
    app.requests.services.BuyerRequestService.create_reroute_request) for
    an item that genuinely exhausted the direct candidate lookup. Called
    from attempt_reroute right before each UNFULFILLED return that
    represents real exhaustion (not the SELLER_ONLY short-circuit, which
    never reaches this) -- and from FulfilmentService.recover_stuck_allocations
    (14.3), which resolves a REROUTING allocation stranded past its item's
    fulfilment deadline the same way attempt_reroute itself would have.
    Public (not module-private) specifically for that second, cross-module
    caller.

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

            order_id = order_item.order_id
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

        with session_scope() as session:
            OrderEventService.emit(
                session,
                order_id=order_id,
                order_item_id=order_item_id,
                event_type=OrderEventType.ITEM_ESCALATED,
                actor_type=ActorType.SYSTEM,
                metadata={"market_id": market_id, "category_id": category_id},
            )
    except Exception:
        logger.exception(
            "Failed to escalate unfulfilled allocation %s to Buyer Requests",
            failed_allocation_id,
        )


def _latest_allocation(session, order_item_id: int) -> Optional[FulfilmentAllocation]:
    return (
        session.query(FulfilmentAllocation)
        .filter_by(order_item_id=order_item_id)
        .order_by(FulfilmentAllocation.created_at.desc())
        .first()
    )


def get_item_escalation(order_item_id: int, buyer_id: int) -> dict:
    """7.3: buyer-facing view of an item Markt couldn't find a
    replacement seller for -- surfaces the auto-generated reroute
    BuyerRequest (escalate_unfulfilled_item above) and its pending offers
    so the buyer can choose a replacement seller (7.3 option 1) directly
    from the order, rather than having to find it buried in their general
    /requests list. "Escalated" here means the item's most recent
    FulfilmentAllocation is UNFULFILLED and the item itself hasn't
    already been resolved (removed/cancelled) -- the same state
    escalate_unfulfilled_item itself acts on.

    Only 3 of 7.3's 4 options are surfaced by this module (this one, plus
    remove_escalated_item below, plus the existing whole-order
    OrderService.cancel_order): "source from a second market for a fee"
    needs a real cross-market delivery-fee calculation that doesn't exist
    yet (CartService._calculate_shipping_fee is still a flat-rate stub --
    same gap already flagged against Phase 13's multi-market basket UI).
    Offering that choice without a real fee behind it would be dishonest,
    so it's left out rather than faked.
    """
    with session_scope() as session:
        order_item = (
            session.query(OrderItem)
            .options(db.joinedload(OrderItem.order))
            .get(order_item_id)
        )
        if not order_item:
            raise NotFoundError("Order item not found")
        if not order_item.order or order_item.order.buyer_id != buyer_id:
            raise ForbiddenError("You can only view your own order items")

        latest = _latest_allocation(session, order_item_id)
        escalated = bool(
            latest
            and latest.status == FulfilmentAllocationStatus.UNFULFILLED
            and order_item.status != OrderItem.Status.CANCELLED
        )

        result = {
            "order_item_id": order_item.id,
            "order_id": order_item.order_id,
            "product_id": order_item.product_id,
            "quantity": order_item.quantity,
            "price": order_item.price,
            "item_status": order_item.status.value,
            "escalated": escalated,
            "reroute_request": None,
        }
        if not escalated:
            return result

        from app.requests.models import BuyerRequest, RequestStatus, SellerOffer
        from app.requests.services import OfferStatus

        reroute_request = (
            session.query(BuyerRequest)
            .options(db.joinedload(BuyerRequest.offers).joinedload(SellerOffer.seller))
            .filter_by(order_item_id=order_item_id, status=RequestStatus.OPEN)
            .order_by(BuyerRequest.created_at.desc())
            .first()
        )
        if reroute_request:
            result["reroute_request"] = {
                "id": reroute_request.id,
                "status": reroute_request.status.value,
                "expires_at": (
                    reroute_request.expires_at.isoformat()
                    if reroute_request.expires_at
                    else None
                ),
                "offers": [
                    {
                        "id": offer.id,
                        "seller_id": offer.seller_id,
                        "seller_name": (
                            offer.seller.shop_name if offer.seller else None
                        ),
                        "product_id": offer.product_id,
                        "price": offer.price,
                        "message": offer.message,
                        "status": offer.status.value,
                    }
                    for offer in reroute_request.offers
                    if offer.status == OfferStatus.PENDING
                ],
            }
        return result


def remove_escalated_item(
    order_item_id: int, buyer_id: int, reason: Optional[str] = None
) -> dict:
    """7.3 option: buyer removes an item Markt couldn't find a
    replacement seller for, refunding just that item without cancelling
    the rest of the order. Reuses OrderService.refund_unresolved_item
    (11.8/9.1's same primitive) but adds the ownership + eligibility
    check that primitive doesn't have on its own -- its only prior
    callers are trusted system workers, not a buyer-facing HTTP request.

    Also closes the open reroute BuyerRequest (if one exists) so a seller
    can't have a stale offer accepted against an item that's already been
    removed and refunded -- best-effort, logged rather than raised on
    failure, since the item removal/refund itself is the part that must
    not be rolled back or masked.
    """
    with session_scope() as session:
        order_item = (
            session.query(OrderItem)
            .options(
                db.joinedload(OrderItem.order).joinedload(Order.buyer),
            )
            .get(order_item_id)
        )
        if not order_item:
            raise NotFoundError("Order item not found")
        if not order_item.order or order_item.order.buyer_id != buyer_id:
            raise ForbiddenError("You can only manage your own order items")
        if order_item.status == OrderItem.Status.CANCELLED:
            raise ConflictError("This item has already been removed")

        latest = _latest_allocation(session, order_item_id)
        if not latest or latest.status != FulfilmentAllocationStatus.UNFULFILLED:
            raise ValidationError(
                "This item isn't in an escalated state -- nothing to remove"
            )

        buyer_user_id = (
            order_item.order.buyer.user_id if order_item.order.buyer else None
        )

    from app.orders.services import OrderService

    OrderService.refund_unresolved_item(
        order_item_id, reason=reason or "buyer_removed_after_escalation"
    )

    from app.requests.models import BuyerRequest, RequestStatus
    from app.requests.services import BuyerRequestService

    with session_scope() as session:
        open_request = (
            session.query(BuyerRequest)
            .filter_by(order_item_id=order_item_id, status=RequestStatus.OPEN)
            .first()
        )
        request_id = open_request.id if open_request else None

    if request_id and buyer_user_id:
        try:
            BuyerRequestService.update_request_status(
                request_id, buyer_user_id, RequestStatus.CLOSED
            )
        except Exception:
            logger.exception(
                "Failed to close reroute request %s after removing item %s",
                request_id,
                order_item_id,
            )

    return {"order_item_id": order_item_id, "status": "removed"}


class ReroutingService:
    @staticmethod
    def attempt_reroute(failed_allocation_id: int) -> Optional[FulfilmentAllocation]:
        """7.1 steps 2-9: called when an allocation lands at DECLINED,
        TIMEOUT, BUYER_REJECTED (6.1's ASK-gate rejection -- see
        FulfilmentService.buyer_reject_reroute), or CANCELLED_BY_SELLER
        (13.4 anti-gaming "accept-then-cancel" -- see
        FulfilmentService.cancel_after_accept). Finds and ranks eligible
        in-market candidates (excluding every seller already tried for
        this item) and reserves stock against the top-ranked one, retrying
        down the ranked list if a reservation loses a race. Returns the
        new AWAITING_SELLER allocation on success.

        Returns None if the item couldn't be rerouted -- SELLER_ONLY
        preference (7.1 step 2), fulfilment deadline or retry limit
        reached, or no eligible candidates at all -- after marking the
        failed allocation UNFULFILLED. 7.3's escalation flow (surfacing
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

            # 7.1 step 2: SELLER_ONLY means no rerouting at all -- skip
            # straight to the same UNFULFILLED end state 7.3's (unbuilt)
            # escalation flow would pick up from, without even looking for
            # candidates.
            if order_item.fulfilment_preference == FulfilmentPreference.SELLER_ONLY:
                failed.transition_to(FulfilmentAllocationStatus.REROUTING)
                failed.transition_to(FulfilmentAllocationStatus.UNFULFILLED)
                OrderEventService.emit(
                    session,
                    order_id=order_item.order_id,
                    order_item_id=order_item.id,
                    event_type=OrderEventType.ITEM_UNFULFILLED,
                    actor_type=ActorType.SYSTEM,
                    metadata={"reason": "seller_only_preference"},
                )
                session.flush()
                _notify_buyer_item_unfulfilled(order_item, "seller_only_preference")
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
                OrderEventService.emit(
                    session,
                    order_id=order_item.order_id,
                    order_item_id=order_item.id,
                    event_type=OrderEventType.ITEM_UNFULFILLED,
                    actor_type=ActorType.SYSTEM,
                    metadata={"reason": "deadline_or_retry_limit_reached"},
                )
                session.flush()
                _notify_buyer_item_unfulfilled(
                    order_item, "deadline_or_retry_limit_reached"
                )
                escalate_unfulfilled_item(failed_allocation_id)
                return None

            original_product = session.query(Product).get(order_item.product_id)
            if not original_product:
                failed.transition_to(FulfilmentAllocationStatus.UNFULFILLED)
                OrderEventService.emit(
                    session,
                    order_id=order_item.order_id,
                    order_item_id=order_item.id,
                    event_type=OrderEventType.ITEM_UNFULFILLED,
                    actor_type=ActorType.SYSTEM,
                    metadata={"reason": "original_product_missing"},
                )
                session.flush()
                _notify_buyer_item_unfulfilled(order_item, "original_product_missing")
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
                OrderEventService.emit(
                    session,
                    order_id=order_item.order_id,
                    order_item_id=order_item.id,
                    event_type=OrderEventType.ITEM_UNFULFILLED,
                    actor_type=ActorType.SYSTEM,
                    metadata={"reason": "no_eligible_candidates"},
                )
                session.flush()
                _notify_buyer_item_unfulfilled(order_item, "no_eligible_candidates")
                escalate_unfulfilled_item(failed_allocation_id)
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
                order_item = session.query(OrderItem).get(failed.order_item_id)
                if order_item:
                    OrderEventService.emit(
                        session,
                        order_id=order_item.order_id,
                        order_item_id=order_item.id,
                        event_type=OrderEventType.ITEM_UNFULFILLED,
                        actor_type=ActorType.SYSTEM,
                        metadata={"reason": "every_candidate_lost_stock_race"},
                    )
                    _notify_buyer_item_unfulfilled(
                        order_item, "every_candidate_lost_stock_race"
                    )

        escalate_unfulfilled_item(failed_allocation_id)
        return None
