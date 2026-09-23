"""Seller ranking scorer (13.1), applied only after the hard eligibility
filter (7.2) -- a high score never overrides a failed eligibility check
(candidates reaching this module are assumed already eligible).

Distance/Delivery Cost has no real signal yet: rerouting is within one
market, and per-order delivery cost is governed by the shared
DeliveryRun (10), not by which seller within the market fulfils a given
item -- a real per-seller routing cost needs DeliveryRun/route data that
doesn't exist yet (Phase 9). Falls back to the same neutral-prior
convention used everywhere else this session has hit a similar gap
(Phase 3's Historical Inventory Accuracy, this phase's own Inventory
Accuracy in Seller Reliability).
"""

from typing import Any, Dict, List, Optional

from app.inventory.confidence import InventoryConfidenceService
from app.inventory.services import InventoryService
from app.products.models import Product

from .reliability import SellerReliabilityService
from .rerouting import PRICE_HEADROOM_RATE

# 13.3: splitting one item across sellers adds operational complexity,
# so a candidate that can't cover the full needed quantity alone (and
# would therefore require splitting with another seller) is penalised in
# ranking -- not excluded, since a split may still be the only way to
# fulfil the shortfall (5.2), just deprioritised versus a candidate who
# can take the whole thing.
QUANTITY_SPLIT_PENALTY = 0.10

# 13.1 weights.
WEIGHTS = {
    "inventory_confidence": 0.30,
    "seller_reliability": 0.25,
    "distance_delivery_cost": 0.20,
    "price_compatibility": 0.15,
    "response_reliability": 0.10,
}

# See module docstring.
DEFAULT_DISTANCE_DELIVERY_COST_SCORE = 0.6


def _price_compatibility(candidate_price: float, original_price: float) -> float:
    """1.0 at or below the original price (as good or better for the
    buyer), decaying linearly to 0.0 at the eligibility filter's own
    price ceiling (Phase 0: 5% headroom) -- so this never contradicts
    what filter_eligible_candidates already allowed through."""
    if original_price <= 0:
        return 0.0
    if candidate_price <= original_price:
        return 1.0

    ceiling = original_price * (1 + PRICE_HEADROOM_RATE)
    if candidate_price >= ceiling:
        return 0.0

    return round(
        1.0 - (candidate_price - original_price) / (ceiling - original_price), 4
    )


def score_candidate(
    product: Product, original_price: float, needed_quantity: Optional[int] = None
) -> Dict[str, Any]:
    """13.1: weighted seller score for one eligible candidate product.

    needed_quantity, if given, triggers the 13.3 quantity-split penalty
    when the candidate can't cover the full amount alone.
    """
    inventory_confidence = InventoryConfidenceService.get_score_for_product(product.id)
    seller_reliability = SellerReliabilityService.get_score(product.seller_id)
    response_reliability = SellerReliabilityService.get_response_rate(product.seller_id)
    price_compatibility = _price_compatibility(product.price, original_price)
    distance_delivery_cost = DEFAULT_DISTANCE_DELIVERY_COST_SCORE

    score = round(
        WEIGHTS["inventory_confidence"] * inventory_confidence
        + WEIGHTS["seller_reliability"] * seller_reliability
        + WEIGHTS["distance_delivery_cost"] * distance_delivery_cost
        + WEIGHTS["price_compatibility"] * price_compatibility
        + WEIGHTS["response_reliability"] * response_reliability,
        4,
    )

    would_split = False
    if needed_quantity is not None:
        available = InventoryService.get_available_quantity(product.id, variant_id=None)
        if available < needed_quantity:
            would_split = True
            score = round(score * (1 - QUANTITY_SPLIT_PENALTY), 4)

    return {
        "product_id": product.id,
        "seller_id": product.seller_id,
        "price": product.price,
        "score": score,
        "would_split": would_split,
        "inventory_confidence": inventory_confidence,
        "seller_reliability": seller_reliability,
        "distance_delivery_cost": distance_delivery_cost,
        "price_compatibility": price_compatibility,
        "response_reliability": response_reliability,
    }


def rank_candidates(
    candidates: List[Product],
    original_price: float,
    needed_quantity: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Score every eligible candidate and return them highest-score
    first. Ties broken by lower price (better for the buyer)."""
    scored = [
        score_candidate(product, original_price, needed_quantity)
        for product in candidates
    ]
    scored.sort(key=lambda s: (-s["score"], s["price"]))
    return scored
