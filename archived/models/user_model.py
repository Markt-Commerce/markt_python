from db import db
from flask_login import UserMixin
import hashlib
import uuid


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone_number = db.Column(db.String(255))
    username = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(
        db.TIMESTAMP, server_default=db.func.current_timestamp(), nullable=False
    )

    is_buyer = db.Column(db.Boolean, default=False)
    is_seller = db.Column(db.Boolean, default=False)

    # Add other common attributes here

    """
    # Define a relationship with the Chat model
    chats = db.relationship('Chat', back_populates='users')
    """
    # Add relationship to Buyer & Seller - One-to-one relationship
    buyer = db.relationship("Buyer", back_populates="user", uselist=False)
    seller = db.relationship("Seller", back_populate="user", useList=False)

    @property
    def current_role(self):
        return getattr(self, "_current_role", None)

    @current_role.setter
    def current_role(self, role):
        self._current_role = role

    def save_to_db(self):
        db.session.add(self)
        db.session.commit()

    def delete_from_db(self):
        db.session.delete(self)
        db.session.commit()

    @staticmethod
    def generate_unique_id():
        unique_id = str(uuid.uuid4()).encode()
        return hashlib.sha256(unique_id).hexdigest()

    @classmethod
    def get_user_location_data(cls):
        data = UserAddress.query.filter_by(id=cls.id)
        return {
            "city": data.city,
            "country": data.country,
            "longtitude": data.longitude,
            "latitude": data.latitude,
            "house_number": data.house_number,
            "state": data.state,
            "street": data.street,
            "postal_code": data.postal_code,
        }


class UserAddress(db.Model):
    __tablename__ = "user_address"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False
    )
    longtitude = db.Column(db.Float)
    latitude = db.Column(db.Float)
    house_number = db.Column(db.Integer)
    street = db.Column(db.String(255))
    city = db.Column(db.String(255))
    state = db.Column(db.String(255))
    country = db.Column(db.String(255))
    postal_code = db.Column(db.Integer)

    def save_to_db(self):
        db.session.add(self)
        db.session.commit()
