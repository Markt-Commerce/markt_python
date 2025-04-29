from db import db
from sqlalchemy.sql import func
import uuid
import random


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.String(400), nullable=False, unique=True)
    name = db.Column(db.String(255), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=True)
    stock_quantity = db.Column(db.Integer, default=0, nullable=False)
    category = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=func.now(), nullable=False)

    # Define seller relationship
    seller_id = db.Column(db.Integer, db.ForeignKey("sellers.id"), nullable=False)
    seller = db.relationship("Seller", back_populates="products")

    # Define relationships (one-many)
    carts = db.relationship("Cart", back_populates="product")
    comments = db.relationship("Comments", back_populates="product")
    image_name_store = db.relationship("ImageNameStore", back_populates="product")

    # Define relationships (many-to-many)
    favorites = db.relationship(
        "Favorite", secondary="favorites_seller_product", back_populates="products"
    )
    orders = db.relationship(
        "Order", secondary="products_orders", back_populates="products"
    )

    @staticmethod
    def generate_unique_id():
        return str(uuid.uuid4())

    @classmethod
    def get_product_by_id(cls, _id):
        return cls.query.filter_by(product_id=_id).first()

    @classmethod
    def get_products_by_seller_id(cls, seller_id):
        return cls.query.filter_by(seller_id=seller_id).all()

    @classmethod
    def get_random_products(cls, bundle_size):
        """
        gets random products in a particular bundle based on the bundle size
        """
        try:
            num_of_products = cls.query.count()
            random_ids = random.sample(range(1, num_of_products), int(bundle_size))
            return cls.query.filter_by(id=random_ids).all()
        except ValueError:
            return []

    @classmethod
    def search_product_using_name(cls, product_name):
        return cls.query.filter(cls.name.like(f"%{product_name}%")).all()

    @classmethod
    def search_product_using_category(cls, category_name):
        return cls.query.filter(cls.name.like(f"%{category_name}%")).all()

    def set_product_id(self):
        self.product_id = self.generate_unique_id()

    def update_product(self, product_data):
        """updates part or all of the current map/session of self(present class)

        only name,description,price,stock_quantity and category can be updated
        """
        try:
            if product_data["name"] is not None and type(product_data["name"]) == str:
                self.name = product_data["name"]
            if (
                product_data["description"] is not None
                and type(product_data["description"]) == str
            ):
                self.description = product_data["description"]
            if product_data["price"] is not None and type(product_data["price"]) == str:
                self.price = product_data["price"]
            if (
                product_data["stock_quantity"] is not None
                and type(product_data["stock_quantity"]) == str
            ):
                self.stock_quantity = product_data["stock_quantity"]
            if (
                product_data["category"] is not None
                and type(product_data["category"]) == str
            ):
                self.category = product_data["category"]
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False

    def save_to_db(self):
        if not self.product_id:
            self.product_id = self.generate_unique_id()
        db.session.add(self)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e

    def delete_from_db(self):
        db.session.delete(self)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e
