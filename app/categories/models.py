from external.database import db
from app.libs.models import BaseModel
from sqlalchemy.dialects.postgresql import JSONB


class Category(BaseModel):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    slug = db.Column(db.String(60), unique=True)
    image_url = db.Column(db.String(255))
    parent_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    is_active = db.Column(db.Boolean, default=True)
    category_metadata = db.Column(JSONB)  # For additional attributes

    # Relationships
    parent = db.relationship("Category", remote_side=[id], back_populates="children")
    children = db.relationship("Category", back_populates="parent")
    products = db.relationship("ProductCategory", back_populates="category")
    requests = db.relationship("BuyerRequest", back_populates="category")

    def __repr__(self):
        return f"<Category {self.name}>"


class ProductCategory(BaseModel):
    __tablename__ = "product_categories"

    product_id = db.Column(
        db.String(12), db.ForeignKey("products.id"), primary_key=True
    )
    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id"), primary_key=True
    )
    is_primary = db.Column(db.Boolean, default=False)

    product = db.relationship("Product", back_populates="categories")
    category = db.relationship("Category", back_populates="products")


class Tag(BaseModel):
    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    slug = db.Column(db.String(60), unique=True)
    description = db.Column(db.Text)

    products = db.relationship("ProductTag", back_populates="tag")


class ProductTag(BaseModel):
    __tablename__ = "product_tags"

    product_id = db.Column(
        db.String(12), db.ForeignKey("products.id"), primary_key=True
    )
    tag_id = db.Column(db.Integer, db.ForeignKey("tags.id"), primary_key=True)

    product = db.relationship("Product", back_populates="tags")
    tag = db.relationship("Tag", back_populates="products")
