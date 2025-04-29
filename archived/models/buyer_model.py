from db import db
from passlib.hash import pbkdf2_sha256
import uuid


class Buyer(db.Model):
    __tablename__ = "buyers"

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(400), nullable=False, unique=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False
    )
    buyername = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    profile_picture = db.Column(db.String(200))

    user_status = db.Column(db.String(255), default="active")

    # Add Buyer-specific attributes here
    shipping_address = db.Column(db.String(255), nullable=True)  # just for test

    # Define back-reference to User
    user = db.relationship("User", back_populates="buyer")

    # Define one-many relationship
    carts = db.relationship("Cart", back_populates="buyer")
    favorites = db.relationship("Favorite", back_populates="buyer")
    buyer_requests = db.relationship("BuyerRequest", back_populates="buyer")
    orders = db.relationship("Order", back_populates="buyer")
    comments = db.relationship("Comments", back_populates="buyer")

    @staticmethod
    def generate_unique_id():
        return str(uuid.uuid4())

    @classmethod
    def find_by_unique_id(cls, unique_id):
        return cls.query.filter_by(unique_id=unique_id).first()

    def set_password(self, password):
        self.password = pbkdf2_sha256.hash(password)

    def check_password(self, password):
        return pbkdf2_sha256.verify(password, self.password)

    def change_status(self, status):
        acceptable_status = ["active", "offline", "standby"]
        if status in acceptable_status:
            self.user_status = status
            db.session.commit()

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
