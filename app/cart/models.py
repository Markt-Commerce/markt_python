from datetime import datetime, timedelta
from external.database import db
from app.libs.money import MONEY
from app.libs.models import BaseModel


CART_TTL = timedelta(days=30)


def _default_expires_at():
    """Evaluated per row.

    This was `default=datetime.utcnow() + timedelta(days=30)` -- an expression,
    so SQLAlchemy stored the *result* as a scalar default computed once when
    this module was imported. Every cart a process created got the same
    timestamp no matter when it was created, and once that moment passed, new
    carts were born already expired.

    That is what made carts pile up: the read path filters on
    `expires_at > now()`, so an expired cart is invisible and the next
    add-to-cart creates another one.
    """
    return datetime.utcnow() + CART_TTL


class Cart(BaseModel):
    __tablename__ = "carts"

    # One live cart per buyer, enforced in the database. Before this, nothing
    # stopped a buyer accumulating rows, and the various `.first()` lookups
    # could each land on a different one -- checkout would clear one cart
    # while the app read another.
    __table_args__ = (db.UniqueConstraint("buyer_id", name="uq_carts_buyer_id"),)

    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("buyers.id"))
    expires_at = db.Column(db.DateTime, default=_default_expires_at)
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

    def clear_cart(self):
        """Clear cart items from database and cache"""
        from external.redis import redis_client
        from external.database import db

        # Delete from database
        db.session.query(CartItem).filter_by(cart_id=self.id).delete()

        # Delete from Redis cache if exists
        redis_client.client.delete(f"cart:{self.buyer_id}")

        db.session.commit()


class CartItem(BaseModel):
    __tablename__ = "cart_items"

    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("carts.id"))
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"))
    variant_id = db.Column(
        db.Integer, db.ForeignKey("product_variants.id"), nullable=True
    )
    quantity = db.Column(db.Integer, default=1)
    product_price = db.Column(MONEY)  # Snapshot of price at time of adding

    cart = db.relationship("Cart", back_populates="items")
    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")
