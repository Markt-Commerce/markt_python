from enum import Enum
from external.database import db
from app.libs.models import BaseModel
from app.libs.helpers import UniqueIdMixin
from sqlalchemy.dialects.postgresql import JSONB


class RequestStatus(Enum):
    OPEN = "open"
    FULFILLED = "fulfilled"
    CLOSED = "closed"
    EXPIRED = "expired"


class BuyerRequest(BaseModel, UniqueIdMixin):
    __tablename__ = "buyer_requests"
    id_prefix = "REQ_"

    id = db.Column(db.String(12), primary_key=True, default=None)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    budget = db.Column(db.Float)
    status = db.Column(db.Enum(RequestStatus), default=RequestStatus.OPEN)
    request_metadata = db.Column(JSONB)  # For attributes, images etc
    expires_at = db.Column(db.DateTime)

    # Social features
    upvotes = db.Column(db.Integer, default=0)
    views = db.Column(db.Integer, default=0)

    # Relationships
    user = db.relationship("User", back_populates="requests")
    categories = db.relationship("RequestCategory", back_populates="request")
    # comments = db.relationship("RequestComment", back_populates="request")
    offers = db.relationship("SellerOffer", back_populates="request")
    images = db.relationship("RequestImage", back_populates="request")

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, onupdate=db.func.now())


class SellerOffer(BaseModel):
    __tablename__ = "seller_offers"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(12), db.ForeignKey("buyer_requests.id"))
    seller_id = db.Column(db.Integer, db.ForeignKey("sellers.id"))
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"), nullable=True)
    price = db.Column(db.Float)
    message = db.Column(db.Text)
    status = db.Column(db.String(20), default="pending")  # pending/accepted/rejected

    request = db.relationship("BuyerRequest", back_populates="offers")
    seller = db.relationship("Seller", back_populates="offers")
    product = db.relationship("Product")
