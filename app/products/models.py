from enum import Enum

from external.database import db
from app.libs.models import BaseModel, StatusMixin
from app.libs.helpers import UniqueIdMixin

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import func, select


class ProductStatus(Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"
    OUT_OF_STOCK = "out_of_stock"


class Product(BaseModel, StatusMixin, UniqueIdMixin):
    __tablename__ = "products"
    id_prefix = "PRD_"

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

    # Computed count properties
    @hybrid_property
    def view_count(self):
        """Get the count of likes for this product"""
        return len(self.views) if self.views else 0

    @view_count.expression
    def view_count(cls):
        """SQL expression for view count"""
        from app.socials.models import ProductView

        return (
            select(func.count(ProductView.id))
            .where(ProductView.product_id == cls.id)
            .correlate(cls)
            .scalar_subquery()  # or `.as_scalar()` for older versions
        )

    @hybrid_property
    def like_count(self):
        """Get the count of likes for this product"""
        return len(self.likes) if self.likes else 0

    @like_count.expression
    def like_count(cls):
        """SQL expression for like count"""
        from app.socials.models import ProductLike

        return (
            db.session.query(func.count(ProductLike.product_id))
            .filter(ProductLike.product_id == cls.id)
            .label("like_count")
        )

    @hybrid_property
    def comment_count(self):
        """Get the count of comments for this product"""
        return len(self.comments) if self.comments else 0

    @comment_count.expression
    def comment_count(cls):
        """SQL expression for comment count"""
        from app.socials.models import ProductComment

        return (
            db.session.query(func.count(ProductComment.product_id))
            .filter(ProductComment.product_id == cls.id)
            .label("comment_count")
        )


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
