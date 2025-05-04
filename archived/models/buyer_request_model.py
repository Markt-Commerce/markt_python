from db import db
from sqlalchemy.sql import func
import uuid


class BuyerRequest(db.Model):
    __tablename__ = "buyer_request"

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(400), nullable=False, unique=True)
    product_description = db.Column(db.String(400), nullable=False)
    category = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=func.now(), nullable=False)
    status = db.Column(db.String(255), default="open")

    # Define buyer relationship
    buyer_id = db.Column(db.Integer, db.ForeignKey("buyers.id"), nullable=False)
    buyer = db.relationship("Buyer", back_populates="buyer_requests")

    # Define seller relationship (many-many)
    sellers = db.relationship(
        "Seller", secondary="seller_buyer_query", back_populates="buyer_requests"
    )

    @staticmethod
    def generate_unique_id():
        return str(uuid.uuid4())

    @classmethod
    def get_requests_through_id(cls, _id):
        return cls.query.filter_by(unique_id=_id).all()

    @classmethod
    def get_requests_through_buyer_id(cls, buyer_id):
        return cls.query.filter_by(buyer_id=buyer_id).all()

    @classmethod
    def get_requests_using_category(cls, *args):
        return cls.query.filter(cls.category.in_(args)).all()

    @classmethod
    def delete_all_buyer_requests(cls, buyer_id):
        return cls.query.filter_by(buyer_id=buyer_id).delete()

    def save_to_db(self):
        if not self.unique_id:
            self.unique_id = self.generate_unique_id()
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
