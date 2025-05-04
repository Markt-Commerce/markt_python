from db import db
from sqlalchemy.sql import func
import uuid


class Comments(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.String(400), nullable=False, unique=True)
    comment_title = db.Column(db.String(400), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("buyers.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("sellers.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=func.now(), nullable=False)

    # Define buyer relationship
    buyer = db.relationship("Buyer", back_populates="comments")
    # Define product relationship
    product = db.relationship("Product", back_populates="comments")
    # define seller relationship
    seller = db.relationship("Seller", back_populates="comments")

    @staticmethod
    def generate_unique_id():
        return str(uuid.uuid4())

    @classmethod
    def get_comments_by_product_id(cls, product_id):
        return cls.query.filter_by(product_id=product_id).all()

    @classmethod
    def get_comments_by_buyer_id(cls, buyer_id):
        return cls.query.filter_by(buyer_id=buyer_id).all()

    @classmethod
    def get_product_comments(cls, product_id):
        return cls.query.filter_by(comment_place_id=product_id).all()

    @classmethod
    def get_seller_comments(cls, seller_id):
        return cls.query.filter_by(comment_place_id=seller_id).all()

    def save_to_db(self):
        if not self.comment_id:
            self.comment_id = self.generate_unique_id()
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
