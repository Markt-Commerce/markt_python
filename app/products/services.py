# python imports
import logging

# package imports
from sqlalchemy import or_, and_

# project imports
from external.database import db
from app.libs.session import session_scope

# app imports
from .models import Product, ProductVariant, ProductInventory


logger = logging.getLogger(__name__)


class ProductService:
    @staticmethod
    def get_all_products():
        with session_scope() as session:
            return session.query(Product).filter_by(status=Product.Status.ACTIVE).all()

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
                    if k in ["compare_at_price", "sku", "barcode", "weight"]
                }
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
