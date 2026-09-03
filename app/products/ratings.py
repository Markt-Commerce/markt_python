"""Rating aggregates, computed from the database.

Ratings were previously derived two different ways that could disagree:

* ``Product.average_rating`` is a hybrid property over ``product_reviews`` --
  correct, and the only thing that survives a Redis flush.
* ``product:{id}:stats`` in Redis was incremented on write and never
  reconciled, so ``ProductStatsService.update_product_stats`` recomputed the
  average from numbers that only Redis had. Evict the key and every product
  silently drops to 0 stars while the reviews sit untouched in Postgres.

Meanwhile ``Seller.total_rating`` and ``Seller.total_raters`` were read in five
places, serialised into the API, rendered in the mobile app, and used as the
*default* sort for the shop directory -- but no code path ever wrote them. Every
seller showed 0.00, and "sort by rating" ordered by a column of zeros.

This module makes Postgres the single source of truth and treats Redis as a
cache that can be rebuilt from it at any time.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from sqlalchemy import func

from external.database import db
from external.redis import redis_client

logger = logging.getLogger(__name__)

# Kept in sync with the key ProductStatsService already uses, so existing
# readers pick up the corrected values without changing.
PRODUCT_STATS_KEY = "product:{product_id}:stats"


def product_rating_from_db(session, product_id: str) -> Dict[str, float]:
    """Average, rating count and review count for one product, straight from SQL."""
    from app.socials.models import ProductReview

    row = (
        session.query(
            func.coalesce(func.sum(ProductReview.rating), 0),
            func.count(ProductReview.rating),
            func.count(ProductReview.id),
        )
        .filter(ProductReview.product_id == product_id)
        .one()
    )
    rating_sum, rating_count, review_count = int(row[0]), int(row[1]), int(row[2])
    return {
        "rating_sum": rating_sum,
        "rating_count": rating_count,
        "review_count": review_count,
        "avg_rating": round(rating_sum / rating_count, 2) if rating_count else 0.0,
    }


def refresh_product_rating(session, product_id: str) -> Dict[str, float]:
    """Recompute a product's rating from the database and refresh the cache.

    Safe to call repeatedly and safe to call after Redis has been wiped -- it
    never reads the cached counters, it overwrites them.
    """
    stats = product_rating_from_db(session, product_id)
    try:
        redis_client.hset(
            PRODUCT_STATS_KEY.format(product_id=product_id),
            mapping={
                "rating_sum": stats["rating_sum"],
                "rating_count": stats["rating_count"],
                "review_count": stats["review_count"],
                "avg_rating": stats["avg_rating"],
            },
        )
    except Exception as exc:
        # The database already has the truth. A cache write failing must not
        # fail the request that produced the review.
        logger.warning("Could not cache rating stats for %s: %s", product_id, exc)
    return stats


def refresh_seller_rating(session, seller_id: int) -> Dict[str, float]:
    """Recompute a seller's aggregate rating across all of their products.

    Writes ``Seller.total_rating`` and ``Seller.total_raters`` -- the columns the
    shop directory sorts on and the profile displays. Nothing wrote them before,
    which is why every shop showed 0.00.
    """
    from app.products.models import Product
    from app.socials.models import ProductReview
    from app.users.models import Seller

    row = (
        session.query(
            func.coalesce(func.sum(ProductReview.rating), 0),
            func.count(ProductReview.rating),
        )
        .join(Product, Product.id == ProductReview.product_id)
        .filter(Product.seller_id == seller_id, ProductReview.rating.isnot(None))
        .one()
    )
    total_rating, total_raters = int(row[0]), int(row[1])

    seller = session.query(Seller).get(seller_id)
    if seller is not None:
        seller.total_rating = total_rating
        seller.total_raters = total_raters

    return {
        "total_rating": total_rating,
        "total_raters": total_raters,
        "average_rating": (
            round(total_rating / total_raters, 2) if total_raters else 0.0
        ),
    }


def refresh_for_product(session, product_id: str) -> Dict[str, float]:
    """Refresh both the product's and its seller's aggregates.

    Call after any write that changes a review's rating: create, edit, delete.
    Returns the product's stats.
    """
    stats = refresh_product_rating(session, product_id)

    from app.products.models import Product

    seller_id: Optional[int] = (
        session.query(Product.seller_id).filter(Product.id == product_id).scalar()
    )
    if seller_id is not None:
        refresh_seller_rating(session, seller_id)
    return stats


def backfill_all(session) -> Dict[str, int]:
    """Recompute every product and seller aggregate from scratch.

    For the one-off repair of sellers whose columns were never populated, and as
    the recovery path if the cache is ever lost.
    """
    from app.products.models import Product
    from app.users.models import Seller

    product_ids = [pid for (pid,) in session.query(Product.id).all()]
    for product_id in product_ids:
        refresh_product_rating(session, product_id)

    seller_ids = [sid for (sid,) in session.query(Seller.id).all()]
    for seller_id in seller_ids:
        refresh_seller_rating(session, seller_id)

    return {"products": len(product_ids), "sellers": len(seller_ids)}
