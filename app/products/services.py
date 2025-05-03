# python imports
import logging

# package imports
from sqlalchemy import or_, and_

# project imports
from external.database import db
from app.libs.session import session_scope
from app.libs.pagination import Paginator
from app.categories.models import ProductCategory, ProductTag

# app imports
from .models import Product, ProductVariant, ProductInventory
from .constants import PRODUCT_FILTER_KEYS, OPTIONAL_PRODUCT_FIELDS


logger = logging.getLogger(__name__)


class ProductService:
    @staticmethod
    def get_all_products():
        with session_scope() as session:
            return session.query(Product).filter_by(status=Product.Status.ACTIVE).all()

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
    def get_product(product_id):
        with session_scope() as session:
            return (
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

    @staticmethod
    def create_product(product_data, seller_id):
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

    # TODO: Add search, filtering, pagination
