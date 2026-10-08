"""Inventory Confidence (8.3): a transparent, deterministic estimate of
whether a seller can actually supply a listed product right now, and the
cold-start prior (8.4) used before a product/seller has enough observed
history to score for real.
"""

from datetime import datetime, timedelta
from typing import Optional

from external.database import db
from app.libs.errors import NotFoundError, ValidationError
from app.libs.session import session_scope
from app.categories.models import ProductCategory
from app.orders.models import OrderItem
from app.products.models import Product

from .models import CategoryConfidencePrior, InventoryConfidenceScore

# 8.3 weights -- confirmed as spec defaults in Phase 0.
WEIGHTS = {
    "recency": 0.40,
    "accuracy": 0.30,
    "fulfilment": 0.20,
    "activity": 0.10,
}

# Recency/activity decay window: full score if the signal happened within
# RECENCY_FULL_HOURS, decaying linearly to 0 by RECENCY_ZERO_HOURS.
RECENCY_FULL_HOURS = 24
RECENCY_ZERO_HOURS = 24 * 30  # 30 days

# Lookback window for the fulfilment-rate component.
FULFILMENT_LOOKBACK_DAYS = 30

# Global fallback prior when a product has no category, or its category
# has no seeded prior yet. Comfortably mid-band ("Medium") so a brand-new
# seller is never scored Low by default -- Phase 0: "new sellers/products
# must not get the lowest score."
DEFAULT_PRIOR = 0.6

# Confidence bands gate how Markt secures stock (8.3).
HIGH_THRESHOLD = 0.7
MEDIUM_THRESHOLD = 0.4


class ConfidenceBand:
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def get_confidence_band(score: float) -> str:
    if score >= HIGH_THRESHOLD:
        return ConfidenceBand.HIGH
    if score >= MEDIUM_THRESHOLD:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


def _decay(age_hours: float) -> float:
    if age_hours <= RECENCY_FULL_HOURS:
        return 1.0
    if age_hours >= RECENCY_ZERO_HOURS:
        return 0.0
    span = RECENCY_ZERO_HOURS - RECENCY_FULL_HOURS
    return round(1.0 - (age_hours - RECENCY_FULL_HOURS) / span, 4)


class InventoryConfidenceService:
    @staticmethod
    def get_category_prior(session, product_id: str) -> float:
        """8.4 cold start: seed from the product's primary category (or
        any category it has), or the global default if it has none or no
        prior has been seeded for that category yet."""
        product_category = (
            session.query(ProductCategory)
            .filter_by(product_id=product_id, is_primary=True)
            .first()
        )
        if not product_category:
            product_category = (
                session.query(ProductCategory).filter_by(product_id=product_id).first()
            )
        if not product_category:
            return DEFAULT_PRIOR

        prior = (
            session.query(CategoryConfidencePrior)
            .filter_by(category_id=product_category.category_id)
            .first()
        )
        return prior.prior_score if prior else DEFAULT_PRIOR

    @staticmethod
    def seed_category_prior(
        category_id: int, prior_score: float = DEFAULT_PRIOR
    ) -> CategoryConfidencePrior:
        """Seed (or update) a category's cold-start prior."""
        if not 0 <= prior_score <= 1:
            raise ValidationError(f"prior_score must be in [0, 1], got {prior_score}")

        with session_scope() as session:
            prior = (
                session.query(CategoryConfidencePrior)
                .filter_by(category_id=category_id)
                .first()
            )
            if prior:
                prior.prior_score = prior_score
            else:
                prior = CategoryConfidencePrior(
                    category_id=category_id, prior_score=prior_score
                )
                session.add(prior)
            session.flush()
            return prior

    @staticmethod
    def _recency_component(product: Product, now: datetime) -> float:
        if not product.updated_at:
            return 0.0
        age_hours = (now - product.updated_at).total_seconds() / 3600
        return _decay(age_hours)

    @staticmethod
    def _accuracy_component(session, product_id: str) -> float:
        """Historical Inventory Accuracy has no real data source yet -- that
        needs Phase 6's reroute/fulfilment-outcome tracking (an event for
        "seller claimed stock but couldn't deliver"), which doesn't exist
        in this codebase yet. Until then this always returns the cold-start
        prior: it's a structural placeholder, not a real measurement.
        Follow-up once Phase 6 lands."""
        return InventoryConfidenceService.get_category_prior(session, product_id)

    @staticmethod
    def _fulfilment_component(
        session, seller_id: int, now: datetime
    ) -> Optional[float]:
        """Fraction of this seller's items over the lookback window that
        reached DELIVERED rather than CANCELLED. None (not 0) when the
        seller has no resolved items yet in the window -- callers should
        fall back to the prior rather than penalise a quiet seller."""
        cutoff = now - timedelta(days=FULFILMENT_LOOKBACK_DAYS)
        rows = (
            session.query(OrderItem.status, db.func.count(OrderItem.id))
            .filter(
                OrderItem.seller_id == seller_id,
                OrderItem.created_at >= cutoff,
                OrderItem.status.in_(
                    [OrderItem.Status.DELIVERED, OrderItem.Status.CANCELLED]
                ),
            )
            .group_by(OrderItem.status)
            .all()
        )
        counts = {status: count for status, count in rows}
        delivered = counts.get(OrderItem.Status.DELIVERED, 0)
        cancelled = counts.get(OrderItem.Status.CANCELLED, 0)
        total = delivered + cancelled
        if total == 0:
            return None
        return round(delivered / total, 4)

    @staticmethod
    def _activity_component(session, seller_id: int, now: datetime) -> float:
        """Recency of the seller's most recent order activity, as a proxy
        for whether they're actively operating right now."""
        latest = (
            session.query(db.func.max(OrderItem.created_at))
            .filter(OrderItem.seller_id == seller_id)
            .scalar()
        )
        if not latest:
            return 0.0
        age_hours = (now - latest).total_seconds() / 3600
        return _decay(age_hours)

    @staticmethod
    def calculate_score(product_id: str) -> InventoryConfidenceScore:
        """Recompute and persist the confidence score for one product."""
        now = datetime.utcnow()
        with session_scope() as session:
            product = session.query(Product).get(product_id)
            if not product:
                raise NotFoundError(f"Product {product_id} not found")

            recency = InventoryConfidenceService._recency_component(product, now)
            accuracy = InventoryConfidenceService._accuracy_component(
                session, product_id
            )

            fulfilment = None
            activity = 0.0
            if product.seller_id:
                fulfilment = InventoryConfidenceService._fulfilment_component(
                    session, product.seller_id, now
                )
                activity = InventoryConfidenceService._activity_component(
                    session, product.seller_id, now
                )
            if fulfilment is None:
                fulfilment = InventoryConfidenceService.get_category_prior(
                    session, product_id
                )

            score = round(
                WEIGHTS["recency"] * recency
                + WEIGHTS["accuracy"] * accuracy
                + WEIGHTS["fulfilment"] * fulfilment
                + WEIGHTS["activity"] * activity,
                4,
            )

            record = (
                session.query(InventoryConfidenceScore)
                .filter_by(product_id=product_id)
                .first()
            )
            if record:
                record.score = score
                record.recency_component = recency
                record.accuracy_component = accuracy
                record.fulfilment_component = fulfilment
                record.activity_component = activity
                record.calculated_at = now
            else:
                record = InventoryConfidenceScore(
                    product_id=product_id,
                    score=score,
                    recency_component=recency,
                    accuracy_component=accuracy,
                    fulfilment_component=fulfilment,
                    activity_component=activity,
                    calculated_at=now,
                )
                session.add(record)

            session.flush()
            return record

    @staticmethod
    def get_score_for_product(product_id: str, session=None) -> float:
        """Last computed confidence score, or the cold-start prior if none
        exists yet -- doesn't force a synchronous calculation.

        Accepts an already-open `session` so a caller mid-transaction
        (InventoryService.reserve_stock's row-locked transaction,
        ReroutingService.attempt_reroute's) doesn't have this open a
        *separate* nested session_scope() of its own -- that would commit
        (and, for reserve_stock, release the row lock backing) the
        caller's own in-progress transaction early. This was a real bug:
        it silently broke reserve_stock's concurrency guarantee (two
        concurrent reservations against stock=1 could both succeed),
        caught by the CI job's disposable-database concurrency test, not
        by any mocked-session unit test -- none of those exercise a real
        transaction/commit boundary."""
        if session is not None:
            record = (
                session.query(InventoryConfidenceScore)
                .filter_by(product_id=product_id)
                .first()
            )
            return (
                record.score
                if record
                else InventoryConfidenceService.get_category_prior(session, product_id)
            )

        with session_scope() as session:
            return InventoryConfidenceService.get_score_for_product(
                product_id, session=session
            )

    @staticmethod
    def get_band_for_product(product_id: str, session=None) -> str:
        """Confidence band for gating (8.3). See get_score_for_product."""
        return get_confidence_band(
            InventoryConfidenceService.get_score_for_product(
                product_id, session=session
            )
        )
