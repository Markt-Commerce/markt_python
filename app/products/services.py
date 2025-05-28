# python imports
import logging
from datetime import datetime, timedelta

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
from app.libs.errors import NotFoundError, ValidationError, ConflictError, APIError

from app.users.models import Seller
from app.socials.models import Follow, Post, PostProduct

# app imports
from .models import Product, ProductVariant, ProductInventory
from .constants import PRODUCT_FILTER_KEYS, OPTIONAL_PRODUCT_FIELDS


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
                "products": result["items"],
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
    def get_seller_posts(seller_id, page=1, per_page=20):
        """Get paginated posts by seller"""
        with session_scope() as session:
            base_query = (
                session.query(Post)
                .filter(Post.seller_id == seller_id, Post.status == "active")
                .options(
                    joinedload(Post.media),
                    joinedload(Post.tagged_products).joinedload(PostProduct.product),
                )
            )

            paginator = Paginator(base_query, page=page, per_page=per_page)
            result = paginator.paginate({})  # Pass empty dict if no filters

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
                    followed_sellers = (
                        session.query(Seller.id)
                        .join(Follow, Follow.followee_id == Seller.user_id)
                        .filter(Follow.follower_id == user_id)
                        .subquery()
                    )

                    query = query.filter(Product.seller_id.in_(followed_sellers))

                return query.order_by(Product.view_count.desc()).limit(limit).all()

        except Exception as e:
            logger.error(f"Product recommendations failed: {str(e)}")
            return []

    @staticmethod
    def get_trending_products(user_id, limit=5):
        """Get trending products with personalization"""
        try:
            # Get from Redis cache
            product_ids = redis_client.zrevrange("trending_products", 0, limit - 1)
            if not product_ids:
                return []

            with session_scope() as session:
                products = (
                    session.query(Product)
                    .filter(Product.id.in_(product_ids))
                    .options(joinedload(Product.seller), joinedload(Product.images))
                    .all()
                )

                # Personalize based on user's preferences
                if user_id:
                    products = ProductService._apply_personalization(products, user_id)

                return [
                    {
                        "type": "product",
                        "data": p,
                        "score": redis_client.zscore("trending_products", p.id),
                        "created_at": p.created_at,
                    }
                    for p in products
                ]

        except Exception as e:
            logger.error(f"Trending products error: {str(e)}")
            return []

    @staticmethod
    def update_trending_products():
        """Update trending products in Redis"""
        try:
            with session_scope() as session:
                # Get products with most engagement in last 7 days
                products = (
                    session.query(Product)
                    .filter(Product.created_at >= datetime.utcnow() - timedelta(days=7))
                    .order_by((Product.view_count + Product.like_count * 2).desc())
                    .limit(50)
                    .all()
                )

                # Update Redis
                with redis_client.pipeline() as pipe:
                    pipe.delete("trending_products")
                    for product in products:
                        score = product.view_count + product.like_count * 2
                        pipe.zadd("trending_products", {product.id: score})
                    pipe.execute()

        except Exception as e:
            logger.error(f"Failed to update trending products: {str(e)}")

    # TODO: Add search, filtering, pagination
