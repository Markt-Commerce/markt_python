from db import db
import uuid


class Favorite(db.Model):
    __tablename__ = "favorites"

    id = db.Column(db.Integer, primary_key=True)
    favorite_id = db.Column(db.String(400), nullable=False, unique=True)
    favorite_item_id = db.Column(
        db.String(400), nullable=False
    )  # the id of the buyer favorite (seller or product)
    favorite_type = db.Column(db.String(400), nullable=False)  # seller or product
    buyer_id = db.Column(db.Integer, db.ForeignKey("buyers.id"), nullable=False)

    # Define buyer relationship
    buyer = db.relationship("Buyer", back_populates="favorites")
    # Define relationships (many-many)
    sellers = db.relationship(
        "Seller", secondary="favorites_seller_product", back_populates="favorites"
    )
    products = db.relationship(
        "Product", secondary="favorites_seller_product", back_populates="favorites"
    )

    @staticmethod
    def generate_unique_id():
        return str(uuid.uuid4())

    @classmethod
    def get_favorite_by_id(cls, _id):
        return cls.query.filter_by(id=_id).first()

    @classmethod
    def get_favorites_by_buyer_id(cls, buyer_id):
        return cls.query.filter_by(buyer_id=buyer_id).all()

    @classmethod
    def delete_all_buyer_favorites(cls, buyer_id):
        return cls.filter_by(buyer_id=buyer_id).delete()

    @classmethod
    def get_all_buyer_favorites_that_are_sellers(cls, buyer_id):
        return (
            cls.query.filter_by(buyer_id=buyer_id).filter(favorite_type="seller").all()
        )

    @classmethod
    def get_all_buyer_favorites_that_are_products(cls, buyer_id):
        return cls.query.filter_by(buyer_id=buyer_id, favorite_type="product").all()

    def save_to_db(self):
        if not self.favorite_id:
            self.favorite_id = self.generate_unique_id()
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
