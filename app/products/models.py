from enum import Enum
from external.database import db
from app.libs.models import BaseModel, StatusMixin
from app.libs.helper import UniqueIdMixin
from sqlalchemy.dialects.postgresql import JSONB


class ProductStatus(Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"
    OUT_OF_STOCK = "out_of_stock"


class Product(BaseModel, StatusMixin, UniqueIdMixin):
    __tablename__ = "products"
    id_prefix = "PROD_"

    class Status(Enum):
        ACTIVE = "active"
        DRAFT = "draft"
        ARCHIVED = "archived"
        OUT_OF_STOCK = "out_of_stock"

    id = db.Column(
        db.String(12), primary_key=True, default=None
    )  # Will be auto-generated
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    compare_at_price = db.Column(db.Float)
    cost_per_item = db.Column(db.Float)
    stock = db.Column(db.Integer, default=0)
    sku = db.Column(db.String(50), unique=True)
    barcode = db.Column(db.String(50))
    weight = db.Column(db.Float)  # in grams
    product_metadata = db.Column(JSONB)  # For variants, specs etc

    seller_id = db.Column(db.Integer, db.ForeignKey("sellers.id"))
    seller = db.relationship("Seller", back_populates="products")

    # Relationships
    images = db.relationship(
        "ProductImage", back_populates="product", order_by="ProductImage.sort_order"
    )
    variants = db.relationship("ProductVariant", back_populates="product")
    categories = db.relationship("ProductCategory", back_populates="product")
    tags = db.relationship("ProductTag", back_populates="product")

    # Social features
    likes = db.relationship("ProductLike", back_populates="product")
    comments = db.relationship("ProductComment", back_populates="product")
    # shares = db.relationship("ProductShare", back_populates="product")
    views = db.relationship("ProductView", back_populates="product")

    def is_available(self):
        return self.status == self.Status.ACTIVE and self.stock > 0


class ProductVariant(BaseModel):
    __tablename__ = "product_variants"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"))
    name = db.Column(db.String(50))  # e.g., "Color", "Size"
    options = db.Column(JSONB)  # {"values": ["Red", "Blue"], "prices": [10.99, 12.99]}

    product = db.relationship("Product", back_populates="variants")


class ProductInventory(BaseModel):
    __tablename__ = "product_inventory"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"))
    variant_id = db.Column(
        db.Integer, db.ForeignKey("product_variants.id"), nullable=True
    )
    quantity = db.Column(db.Integer, default=0)
    location = db.Column(db.String(50))  # Warehouse location

    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")
