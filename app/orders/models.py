from enum import Enum
from datetime import datetime
from external.database import db
from app.libs.models import BaseModel, StatusMixin
from app.libs.helpers import UniqueIdMixin
from sqlalchemy.dialects.postgresql import JSONB


class OrderStatus(Enum):
    PENDING_PAYMENT = "pending_payment"  # Order created, waiting for payment
    READY_FOR_DELIVERY = "ready_for_delivery"
    PENDING = "pending"  # Deprecated: Use PENDING_PAYMENT instead
    PROCESSING = "processing"  # Payment confirmed, order being processed
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"
    FAILED = "failed"  # Payment failed or order failed


class Order(BaseModel, UniqueIdMixin):
    __tablename__ = "orders"
    id_prefix = "ORD_"

    id = db.Column(db.String(12), primary_key=True, default=None)
    buyer_id = db.Column(db.Integer, db.ForeignKey("buyers.id"))
    order_number = db.Column(db.String(21), unique=True)
    subtotal = db.Column(db.Float)
    shipping_fee = db.Column(db.Float)
    tax = db.Column(db.Float)
    discount = db.Column(db.Float)
    total = db.Column(db.Float)
    status = db.Column(db.Enum(OrderStatus), default=OrderStatus.PENDING_PAYMENT)
    billing_address = db.Column(JSONB)
    customer_note = db.Column(db.Text)
    idempotency_key = db.Column(
        db.String(100), unique=True, nullable=True
    )  # Prevent duplicate orders
    # Relationships
    buyer = db.relationship("Buyer", back_populates="orders")
    items = db.relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    payments = db.relationship("Payment", back_populates="order")
    shipping_address = db.relationship("ShippingAddress", uselist=False, back_populates="order", cascade="all, delete-orphan")
    shipments = db.relationship("Shipment", back_populates="order")

    def generate_order_number(self):
        # Implement your order number generation logic
        return f"ORD-{datetime.now().strftime('%Y%m%d')}-{self.id.split('_')[1]}"


class OrderItem(BaseModel, StatusMixin):
    __tablename__ = "order_items"

    class Status(Enum):
        PENDING = "pending"
        PROCESSING = "processing"
        SHIPPED = "shipped"
        DELIVERED = "delivered"
        CANCELLED = "cancelled"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(12), db.ForeignKey("orders.id"))
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"))
    variant_id = db.Column(
        db.Integer, db.ForeignKey("product_variants.id"), nullable=True
    )
    seller_id = db.Column(db.Integer, db.ForeignKey("sellers.id"))
    quantity = db.Column(db.Integer)
    price = db.Column(db.Float)

    # Relationships
    order = db.relationship("Order", back_populates="items")
    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")
    seller = db.relationship("Seller")

class ShippingAddress(BaseModel):
    __tablename__ = "shipping_addresses"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(12), db.ForeignKey("orders.id"))
    recipient_name = db.Column(db.String(100))
    street_address = db.Column(db.String(255))
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    postal_code = db.Column(db.String(20))
    country = db.Column(db.String(100))
    # These two are essential for delivery charge calculation and logistics
    # if the longtitude and latitude are not provided, we can use a geocoding service to get them from the address
    longitude = db.Column(db.Float)
    latitude = db.Column(db.Float)

    order = db.relationship("Order", back_populates="shipping_address")

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
