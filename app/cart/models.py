from datetime import datetime, timedelta
from external.database import db
from app.libs.models import BaseModel


class Cart(BaseModel):
    __tablename__ = "carts"

    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("buyers.id"))
    expires_at = db.Column(db.DateTime, default=datetime.utcnow() + timedelta(days=30))
    coupon_code = db.Column(db.String(50))

    # Relationships
    buyer = db.relationship("Buyer", back_populates="carts")
    items = db.relationship(
        "CartItem", back_populates="cart", cascade="all, delete-orphan"
    )

    def total_items(self):
        return sum(item.quantity for item in self.items)

    def subtotal(self):
        return sum(item.product_price * item.quantity for item in self.items)


class CartItem(BaseModel):
    __tablename__ = "cart_items"

    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("carts.id"))
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"))
    variant_id = db.Column(
        db.Integer, db.ForeignKey("product_variants.id"), nullable=True
    )
    quantity = db.Column(db.Integer, default=1)
    product_price = db.Column(db.Float)  # Snapshot of price at time of adding

    cart = db.relationship("Cart", back_populates="items")
    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")
