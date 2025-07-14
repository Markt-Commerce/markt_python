# python imports
import logging
from datetime import datetime
import time
from typing import List, Dict, Any, Optional

# package imports
from sqlalchemy import or_, and_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

# project imports
from external.database import db
from external.redis import redis_client

from app.libs.session import session_scope
from app.libs.pagination import Paginator
from app.categories.models import ProductCategory, ProductTag
from app.libs.errors import (
    NotFoundError,
    ValidationError,
    ConflictError,
    APIError,
    ForbiddenError,
)

from app.users.models import Seller
from app.socials.models import Follow, Post, PostProduct, PostStatus

# app imports
from .models import Product, ProductVariant, ProductInventory
from .constants import PRODUCT_FILTER_KEYS, OPTIONAL_PRODUCT_FIELDS
from app.orders.models import OrderItem


logger = logging.getLogger(__name__)


class ProductService:
    @staticmethod
    def get_all_products():
        try:
            with session_scope() as session:
                products = (
                    session.query(Product).filter_by(status=Product.Status.ACTIVE).all()
                )
                if not products:
                    raise NotFoundError("No products found")
                return products
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching products: {str(e)}")
            raise APIError("Failed to fetch products", 500)

    @staticmethod
    def get_product(product_id):
        try:
            with session_scope() as session:
                product = (
                    session.query(Product)
                    .options(
                        db.joinedload(Product.seller),
                        db.joinedload(Product.variants),
                        db.joinedload(Product.categories).joinedload(
                            ProductCategory.category
                        ),
                    )
                    .get(product_id)
                )
                if not product:
                    raise NotFoundError("Product not found")
                return product
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching product {product_id}: {str(e)}")
            raise APIError("Failed to fetch product", 500)

    @staticmethod
    def search_products(args):
        with session_scope() as session:
            base_query = session.query(Product).filter_by(status=Product.Status.ACTIVE)

            # Initialize paginator
            paginator = Paginator(
                base_query, page=args.get("page", 1), per_page=args.get("per_page", 20)
            )

            # Apply filters
            if PRODUCT_FILTER_KEYS["SEARCH"] in args:
                search = f"%{args[PRODUCT_FILTER_KEYS['SEARCH']]}%"
                paginator.query = paginator.query.filter(
                    or_(Product.name.ilike(search), Product.description.ilike(search))
                )

            if PRODUCT_FILTER_KEYS["MIN_PRICE"] in args:
                paginator.query = paginator.query.filter(
                    Product.price >= args[PRODUCT_FILTER_KEYS["MIN_PRICE"]]
                )

            if PRODUCT_FILTER_KEYS["MAX_PRICE"] in args:
                paginator.query = paginator.query.filter(
                    Product.price <= args[PRODUCT_FILTER_KEYS["MAX_PRICE"]]
                )

            if PRODUCT_FILTER_KEYS["CATEGORY_ID"] in args:
                paginator.query = paginator.query.join(ProductCategory).filter(
                    ProductCategory.category_id
                    == args[PRODUCT_FILTER_KEYS["CATEGORY_ID"]]
                )

            if (
                PRODUCT_FILTER_KEYS["IN_STOCK"] in args
                and args[PRODUCT_FILTER_KEYS["IN_STOCK"]]
            ):
                paginator.query = paginator.query.filter(Product.stock > 0)

            # Apply sorting
            sort_map = {
                "newest": Product.created_at.desc(),
                "popular": Product.view_count.desc(),
                "price_asc": Product.price.asc(),
                "price_desc": Product.price.desc(),
            }

            if "sort_by" in args and args["sort_by"] in sort_map:
                paginator.query = paginator.query.order_by(sort_map[args["sort_by"]])

            # Get paginated results
            result = paginator.paginate(args)

            return {
                "items": result["items"],
                "pagination": {
                    "page": result["page"],
                    "per_page": result["per_page"],
                    "total_items": result["total_items"],
                    "total_pages": result["total_pages"],
                },
            }

    @staticmethod
    def create_product(product_data, seller_id):
        try:
            with session_scope() as session:
                product = Product(
                    name=product_data["name"],
                    description=product_data.get("description"),
                    price=product_data["price"],
                    stock=product_data.get("stock", 0),
                    seller_id=seller_id,
                    **{
                        k: v
                        for k, v in product_data.items()
                        if k in OPTIONAL_PRODUCT_FIELDS
                    },
                )
                session.add(product)
                session.flush()  # Get product ID

                # Handle variants if provided
                if "variants" in product_data:
                    for variant_data in product_data["variants"]:
                        variant = ProductVariant(
                            product_id=product.id,
                            name=variant_data["name"],
                            options=variant_data["options"],
                        )
                        session.add(variant)

                return product
        except SQLAlchemyError as e:
            logger.error(f"Database error creating product: {str(e)}")
            raise APIError("Failed to create product", 500)

    @staticmethod
    def update_product(product_id, seller_id, update_data):
        """Update product details"""
        try:
            with session_scope() as session:
                product = session.query(Product).get(product_id)
                if not product:
                    raise NotFoundError("Product not found")

                if product.seller_id != seller_id:
                    raise ValidationError("You can only update your own products")

                # Update basic fields
                if "name" in update_data:
                    product.name = update_data["name"]
                if "description" in update_data:
                    product.description = update_data["description"]
                if "price" in update_data:
                    product.price = update_data["price"]
                if "stock" in update_data:
                    product.stock = update_data["stock"]
                if "status" in update_data:
                    product.status = update_data["status"]

                # Update optional fields
                for field in OPTIONAL_PRODUCT_FIELDS:
                    if field in update_data:
                        setattr(product, field, update_data[field])

                # Handle variants if provided
                if "variants" in update_data:
                    # Clear existing variants
                    session.query(ProductVariant).filter_by(
                        product_id=product_id
                    ).delete()

                    # Add new variants
                    for variant_data in update_data["variants"]:
                        variant = ProductVariant(
                            product_id=product.id,
                            name=variant_data["name"],
                            options=variant_data["options"],
                        )
                        session.add(variant)

                product.updated_at = datetime.utcnow()
                return product

        except SQLAlchemyError as e:
            logger.error(f"Database error updating product {product_id}: {str(e)}")
            raise APIError("Failed to update product", 500)

    @staticmethod
    def delete_product(product_id, seller_id):
        """Delete product (soft delete)"""
        try:
            with session_scope() as session:
                product = session.query(Product).get(product_id)
                if not product:
                    raise NotFoundError("Product not found")

                if product.seller_id != seller_id:
                    raise ValidationError("You can only delete your own products")

                # Soft delete by changing status
                product.status = Product.Status.DELETED
                product.updated_at = datetime.utcnow()

                # Remove from trending products cache
                redis_client.zrem("trending_products", product_id)

                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error deleting product {product_id}: {str(e)}")
            raise APIError("Failed to delete product", 500)

    @staticmethod
    def bulk_create_products(products_data, seller_id):
        try:
            if not isinstance(products_data, list):
                raise ValidationError("Expected a list of products")

            if len(products_data) > 100:  # Limit to prevent abuse
                raise ValidationError("Cannot create more than 100 products at once")

            results = {"success": [], "errors": []}

            with session_scope() as session:
                for idx, product_data in enumerate(products_data):
                    try:
                        product = Product(
                            name=product_data["name"],
                            description=product_data.get("description"),
                            price=product_data["price"],
                            stock=product_data.get("stock", 0),
                            seller_id=seller_id,
                            **{
                                k: v
                                for k, v in product_data.items()
                                if k in OPTIONAL_PRODUCT_FIELDS
                            },
                        )
                        session.add(product)
                        session.flush()

                        if "variants" in product_data:
                            for variant_data in product_data["variants"]:
                                if not variant_data.get("name") or not variant_data.get(
                                    "options"
                                ):
                                    raise ValidationError(
                                        "Variant requires name and options",
                                        errors={"index": idx},
                                    )

                                variant = ProductVariant(
                                    product_id=product.id,
                                    name=variant_data["name"],
                                    options=variant_data["options"],
                                )
                                session.add(variant)

                        results["success"].append(
                            {
                                "index": idx,
                                "product_id": product.id,
                                "name": product.name,
                            }
                        )

                    except (ValidationError, SQLAlchemyError) as e:
                        session.rollback()  # Rollback only this product's changes
                        error_msg = str(e)
                        if isinstance(e, ValidationError):
                            error_msg = e.message
                            if hasattr(e, "errors"):
                                error_msg = f"{error_msg}: {e.errors}"

                        results["errors"].append(
                            {
                                "index": idx,
                                "error": error_msg,
                                "product_data": product_data,
                            }
                        )
                        continue

                return results

        except SQLAlchemyError as e:
            logger.error(f"Database error in bulk product creation: {str(e)}")
            raise APIError("Failed to create products", 500)

    @staticmethod
    def update_inventory(product_id, variant_id=None, quantity_change=0):
        with session_scope() as session:
            # Update main product stock if no variant
            if not variant_id:
                product = session.query(Product).get(product_id)
                if product:
                    product.stock += quantity_change
                    if product.stock <= 0:
                        product.status = Product.Status.OUT_OF_STOCK
                    return product
                return None

            # Update variant inventory
            inventory = (
                session.query(ProductInventory)
                .filter_by(product_id=product_id, variant_id=variant_id)
                .first()
            )

            if inventory:
                inventory.quantity += quantity_change
            else:
                inventory = ProductInventory(
                    product_id=product_id,
                    variant_id=variant_id,
                    quantity=quantity_change,
                )
                session.add(inventory)

            return inventory

    @staticmethod
    def get_recommended_products(user_id, limit=10):
        """Get personalized product recommendations"""
        try:
            with session_scope() as session:
                # Base query - could be enhanced with ML later
                query = (
                    session.query(Product)
                    .filter(Product.status == Product.Status.ACTIVE)
                    .options(joinedload(Product.seller), joinedload(Product.images))
                )

                # Simple recommendation logic (will enhance later)
                if user_id:
                    # Get products from followed sellers
                    followed_seller_ids = [
                        seller_id[0]
                        for seller_id in session.query(Seller.id)
                        .join(Follow, Follow.followee_id == Seller.user_id)
                        .filter(Follow.follower_id == user_id)
                        .all()
                    ]

                    if followed_seller_ids:
                        query = query.filter(Product.seller_id.in_(followed_seller_ids))

                return query.order_by(Product.view_count.desc()).limit(limit).all()

        except Exception as e:
            logger.error(f"Product recommendations failed: {str(e)}")
            return []

    @staticmethod
    def get_trending_products(user_id=None, limit=5):
        """Get trending products with optional personalization"""
        try:
            # Get top products from Redis
            product_ids = [
                pid.decode()
                for pid in redis_client.zrevrange("trending_products", 0, limit - 1)
            ]

            if not product_ids:
                return []

            # Get full product data
            with session_scope() as session:
                products = (
                    session.query(Product)
                    .filter(Product.id.in_(product_ids))
                    .options(joinedload(Product.seller), joinedload(Product.images))
                    .all()
                )

                # Sort in same order as Redis
                products.sort(key=lambda p: product_ids.index(p.id))

                # Basic personalization
                if user_id:
                    viewed = redis_client.zrange(
                        f"user:{user_id}:viewed_products", 0, -1
                    )
                    viewed = {pid.decode() for pid in viewed}

                    for p in products:
                        if p.id in viewed:
                            p._personalized_score = (
                                redis_client.zscore("trending_products", p.id) * 0.7
                            )  # Reduce score for seen products
                        else:
                            p._personalized_score = (
                                redis_client.zscore("trending_products", p.id) * 1.3
                            )  # Boost new products

                    products.sort(key=lambda p: p._personalized_score, reverse=True)

                return products[:limit]

        except Exception as e:
            logger.error(f"Trending fetch failed: {str(e)}")
            return []

    @staticmethod
    def update_trending_products():
        """Optimized trending products using complete Redis stats"""
        try:
            # Get all active products
            product_ids = [
                p.id
                for p in Product.query.filter_by(status=Product.Status.ACTIVE).all()
            ]

            if not product_ids:
                return

            # Calculate scores in pipeline
            with redis_client.pipeline() as pipe:
                pipe.delete("trending_products_temp")

                for pid in product_ids:
                    # Get all stats in one call
                    stats = redis_client.hgetall(f"product:{pid}:stats")

                    # Default values
                    view_count = int(stats.get(b"view_count", 0))
                    avg_rating = float(stats.get(b"avg_rating", 0))
                    last_viewed = float(stats.get(b"last_viewed", time.time()))

                    # Calculate days since last view
                    days_old = (
                        datetime.now() - datetime.fromtimestamp(last_viewed)
                    ).days

                    # Calculate score (adjust weights as needed)
                    score = (
                        view_count * 0.6
                        + avg_rating * 10  # 60% view count
                        + max(0, (7 - days_old))  # 30% rating (scaled up)
                        * 2  # 10% recency
                    )

                    pipe.zadd("trending_products_temp", {pid: score})

                # Atomic update
                pipe.rename("trending_products_temp", "trending_products")
                pipe.execute()

        except Exception as e:
            logger.error(f"Trending update failed: {str(e)}")

    @staticmethod
    def product_exists(product_id: str) -> bool:
        """Check if a product exists"""
        try:
            with session_scope() as session:
                product = (
                    session.query(Product).filter(Product.id == product_id).first()
                )
                return product is not None
        except Exception as e:
            logger.error(f"Error checking if product exists: {e}")
            return False

    # TODO: Add search, filtering, pagination

    @staticmethod
    def reduce_inventory_for_order(order_items: List[OrderItem]) -> bool:
        """Reduce inventory for order items when payment is successful"""
        try:
            with session_scope() as session:
                for item in order_items:
                    # Get product inventory
                    if item.variant_id:
                        # Reduce variant inventory
                        inventory = (
                            session.query(ProductInventory)
                            .filter_by(
                                product_id=item.product_id, variant_id=item.variant_id
                            )
                            .first()
                        )

                        if inventory:
                            if inventory.quantity < item.quantity:
                                raise ValidationError(
                                    f"Insufficient stock for product {item.product_id} variant {item.variant_id}"
                                )
                            inventory.quantity -= item.quantity
                        else:
                            # Create inventory record if it doesn't exist
                            inventory = ProductInventory(
                                product_id=item.product_id,
                                variant_id=item.variant_id,
                                quantity=0,  # Will be negative after reduction
                            )
                            session.add(inventory)
                    else:
                        # Reduce main product stock
                        product = session.query(Product).get(item.product_id)
                        if not product:
                            raise NotFoundError(f"Product {item.product_id} not found")

                        if product.stock < item.quantity:
                            raise ValidationError(
                                f"Insufficient stock for product {item.product_id}"
                            )

                        product.stock -= item.quantity

                        # Update product status if stock becomes 0
                        if product.stock == 0:
                            product.status = Product.Status.OUT_OF_STOCK

                session.flush()
                logger.info(f"Successfully reduced inventory for order items")
                return True

        except Exception as e:
            logger.error(f"Failed to reduce inventory: {str(e)}")
            raise APIError(f"Inventory reduction failed: {str(e)}", 500)

    @staticmethod
    def check_inventory_availability(order_items: List[OrderItem]) -> bool:
        """Check if all order items have sufficient inventory"""
        try:
            with session_scope() as session:
                for item in order_items:
                    if item.variant_id:
                        # Check variant inventory
                        inventory = (
                            session.query(ProductInventory)
                            .filter_by(
                                product_id=item.product_id, variant_id=item.variant_id
                            )
                            .first()
                        )

                        if not inventory or inventory.quantity < item.quantity:
                            return False
                    else:
                        # Check main product stock
                        product = session.query(Product).get(item.product_id)
                        if not product or product.stock < item.quantity:
                            return False

                return True

        except Exception as e:
            logger.error(f"Failed to check inventory availability: {str(e)}")
            return False

    @staticmethod
    def get_product_inventory(
        product_id: str, variant_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get inventory information for a product"""
        with session_scope() as session:
            if variant_id:
                inventory = (
                    session.query(ProductInventory)
                    .filter_by(product_id=product_id, variant_id=variant_id)
                    .first()
                )

                if inventory:
                    return {
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "quantity": inventory.quantity,
                        "location": inventory.location,
                        "available": inventory.quantity > 0,
                    }
                else:
                    return {
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "quantity": 0,
                        "location": None,
                        "available": False,
                    }
            else:
                product = session.query(Product).get(product_id)
                if product:
                    return {
                        "product_id": product_id,
                        "quantity": product.stock,
                        "available": product.stock > 0,
                        "status": product.status.value,
                    }
                else:
                    raise NotFoundError(f"Product {product_id} not found")

    @staticmethod
    def update_product_stock(
        product_id: str, quantity: int, variant_id: Optional[int] = None
    ):
        """Update product stock (for admin/seller use)"""
        with session_scope() as session:
            if variant_id:
                inventory = (
                    session.query(ProductInventory)
                    .filter_by(product_id=product_id, variant_id=variant_id)
                    .first()
                )

                if inventory:
                    inventory.quantity = max(0, quantity)
                else:
                    inventory = ProductInventory(
                        product_id=product_id,
                        variant_id=variant_id,
                        quantity=max(0, quantity),
                    )
                    session.add(inventory)
            else:
                product = session.query(Product).get(product_id)
                if not product:
                    raise NotFoundError(f"Product {product_id} not found")

                product.stock = max(0, quantity)

                # Update status based on stock
                if product.stock == 0:
                    product.status = Product.Status.OUT_OF_STOCK
                elif product.status == Product.Status.OUT_OF_STOCK:
                    product.status = Product.Status.ACTIVE

            session.flush()
            logger.info(f"Updated stock for product {product_id} to {quantity}")
            return True


class ProductStatsService:
    @staticmethod
    def update_product_stats(product_id):
        """
        Updates derived stats for a product stored in Redis,
        including average rating and last viewed timestamp.
        """
        redis_key = f"product:{product_id}:stats"

        try:
            # Use pipeline to get rating sum and count in one round trip
            with redis_client.pipeline() as pipe:
                pipe.hget(redis_key, "rating_sum")
                pipe.hget(redis_key, "rating_count")
                rating_sum_raw, rating_count_raw = pipe.execute()

            # Decode if Redis returns bytes (depends on decode_responses=True)
            if isinstance(rating_sum_raw, bytes):
                rating_sum_raw = rating_sum_raw.decode()
            if isinstance(rating_count_raw, bytes):
                rating_count_raw = rating_count_raw.decode()

            rating_sum = int(rating_sum_raw) if rating_sum_raw else 0
            rating_count = int(rating_count_raw) if rating_count_raw else 0

            avg_rating = (
                round(rating_sum / rating_count, 2) if rating_count > 0 else 0.0
            )

            # Update stats in Redis
            with redis_client.pipeline() as pipe:
                pipe.hset(redis_key, "avg_rating", avg_rating)
                # pipe.hset(redis_key, "last_updated", time.time())
                pipe.execute()

        except Exception as e:
            logger.warning(f"Failed to update product stats for {product_id}: {e}")
