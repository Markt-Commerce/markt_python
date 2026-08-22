"""Rerouting engine: candidate-seller lookup and the hard eligibility
filter (§7.1 step 3-4, §7.2), now that Market/Area exist
(feat/market-area-foundation) to scope "same market" by.

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
"""

import re
from typing import List, Optional

from app.categories.models import ProductCategory
from app.inventory.confidence import ConfidenceBand, InventoryConfidenceService
from app.products.models import Product
from app.users.models import MarketVerificationStatus, Seller

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
        .filter(
            Product.seller_id != exclude_seller_id,
            Product.status == Product.Status.ACTIVE,
            ProductCategory.category_id == primary_category.category_id,
            Seller.market_id == original_seller.market_id,
            Seller.market_verification_status == MarketVerificationStatus.VERIFIED,
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
