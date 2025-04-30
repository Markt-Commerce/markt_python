from enum import Enum
from datetime import datetime
from external.database import db
from app.libs.models import BaseModel
from app.libs.helper import UniqueIdMixin
from sqlalchemy.dialects.postgresql import JSONB


class OrderStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class Order(BaseModel, UniqueIdMixin):
    __tablename__ = "orders"
    id_prefix = "ORD_"

    id = db.Column(db.String(12), primary_key=True, default=None)
    buyer_id = db.Column(db.Integer, db.ForeignKey("buyers.id"))
    seller_id = db.Column(db.Integer, db.ForeignKey("sellers.id"))
    order_number = db.Column(db.String(20), unique=True)
    subtotal = db.Column(db.Float)
    shipping_fee = db.Column(db.Float)
    tax = db.Column(db.Float)
    discount = db.Column(db.Float)
    total = db.Column(db.Float)
    status = db.Column(db.Enum(OrderStatus), default=OrderStatus.PENDING)
    items = db.Column(JSONB)  # Serialized order items
    shipping_address = db.Column(JSONB)
    billing_address = db.Column(JSONB)
    customer_note = db.Column(db.Text)

    # Relationships
    buyer = db.relationship("Buyer", back_populates="orders")
    seller = db.relationship("Seller", back_populates="orders")
    payments = db.relationship("Payment", back_populates="order")
    shipments = db.relationship("Shipment", back_populates="order")

    def generate_order_number(self):
        # Implement your order number generation logic
        return f"ORD-{datetime.now().strftime('%Y%m%d')}-{self.id:06d}"


class Shipment(BaseModel):
    __tablename__ = "shipments"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(12), db.ForeignKey("orders.id"))
    carrier = db.Column(db.String(50))
    tracking_number = db.Column(db.String(100))
    tracking_url = db.Column(db.String(255))
    status = db.Column(db.String(50))
    shipped_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)

    order = db.relationship("Order", back_populates="shipments")
