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
    # Buyer-facing Service Fee (§11.3, Phase 0: 2.5%, floor ₦25, ceiling
    # ₦1,000). Nullable: orders from the pre-existing order-first checkout
    # flow predate this fee and never set it.
    service_fee = db.Column(db.Float, nullable=True)
    # Reliability Fee (§11.2, Phase 0: 10% of order value, capped ₦1,500) --
    # opt-in, and only ever actually charged if a reroute fires. Rerouting
    # doesn't exist yet (Phase 6), so today this is toggle + estimate only;
    # reliability_fee_estimate is NEVER added to `total`/captured amount.
    reliability_fee_opted_in = db.Column(db.Boolean, default=False, nullable=False)
    reliability_fee_estimate = db.Column(db.Float, nullable=True)
    total = db.Column(db.Float)
    status = db.Column(db.Enum(OrderStatus), default=OrderStatus.PENDING_PAYMENT)
    billing_address = db.Column(JSONB)
    customer_note = db.Column(db.Text)
    idempotency_key = db.Column(
        db.String(100), unique=True, nullable=True
    )  # Prevent duplicate orders
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancel_reason = db.Column(db.Text, nullable=True)
    paystack_split_used = db.Column(db.Boolean, default=False, nullable=False)
    # Relationships
    buyer = db.relationship("Buyer", back_populates="orders")
    items = db.relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    payments = db.relationship("Payment", back_populates="order")
    shipping_address = db.relationship(
        "ShippingAddress",
        uselist=False,
        back_populates="order",
        cascade="all, delete-orphan",
    )
    shipments = db.relationship("Shipment", back_populates="order")
    returns = db.relationship("OrderReturn", back_populates="order", lazy="dynamic")

    def generate_order_number(self):
        # Implement your order number generation logic
        return f"ORD-{datetime.now().strftime('%Y%m%d')}-{self.id.split('_')[1]}"

    @property
    def shipping_address_dict(self):
        """Expose shipping address as a plain dict for schemas that expect a mapping."""
        addr = self.shipping_address
        if not addr:
            return None
        return {
            "recipient_name": addr.recipient_name,
            "street_address": addr.street_address,
            "city": addr.city,
            "state": addr.state,
            "postal_code": addr.postal_code,
            "country": addr.country,
            "latitude": addr.latitude,
            "longitude": addr.longitude,
        }


class OrderItem(BaseModel, StatusMixin):
    __tablename__ = "order_items"

    class Status(Enum):
        PENDING = "pending"
        PROCESSING = "processing"
        SHIPPED = "shipped"
        DELIVERED = "delivered"
        CANCELLED = "cancelled"

    # Single source of truth for legal status transitions, used by every code
    # path that moves an item forward (seller self-reported shipping,
    # Markt-rider pickup/POD) so none of them can drift out of sync with the
    # others. PROCESSING->DELIVERED is allowed directly because a
    # rider-confirmed POD is authoritative even if the pickup step was never
    # separately recorded -- the buyer having the item in hand shouldn't be
    # blocked on earlier bookkeeping.
    VALID_STATUS_TRANSITIONS = {
        Status.PENDING: [Status.PROCESSING, Status.CANCELLED],
        Status.PROCESSING: [Status.SHIPPED, Status.DELIVERED, Status.CANCELLED],
        Status.SHIPPED: [Status.DELIVERED],
    }

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(12), db.ForeignKey("orders.id"))
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"))
    variant_id = db.Column(
        db.Integer, db.ForeignKey("product_variants.id"), nullable=True
    )
    seller_id = db.Column(db.Integer, db.ForeignKey("sellers.id"))
    quantity = db.Column(db.Integer)
    price = db.Column(db.Float)
    # When this item was marked DELIVERED -- starts the settlement hold
    # (Phase 0: 12h). Set by whichever path transitions the item, never by
    # WalletService itself.
    delivered_at = db.Column(db.DateTime, nullable=True)
    # Set once WalletService.settle_order_item has actually run for this
    # item (regardless of whether it paid out or determined nothing was
    # owed) -- lets the settlement worker query "still pending" cheaply
    # without re-deriving that from the wallet ledger.
    settled_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    order = db.relationship("Order", back_populates="items")
    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")
    seller = db.relationship("Seller")

    def transition_to(self, new_status: "OrderItem.Status") -> None:
        """Apply a status change, raising ValueError if it isn't a legal transition."""
        allowed = OrderItem.VALID_STATUS_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(f"Cannot transition from {self.status} to {new_status}")
        self.status = new_status


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


class OrderReturnStatus(Enum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    REFUNDED = "refunded"


class OrderReturn(BaseModel, UniqueIdMixin):
    __tablename__ = "order_returns"
    id_prefix = "RET_"

    id = db.Column(db.String(12), primary_key=True, default=None)
    order_id = db.Column(db.String(12), db.ForeignKey("orders.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("buyers.id"), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(
        db.Enum(OrderReturnStatus), default=OrderReturnStatus.REQUESTED, nullable=False
    )
    refund_amount = db.Column(db.Float, nullable=True)
    seller_notes = db.Column(db.Text, nullable=True)

    order = db.relationship("Order", back_populates="returns")
    buyer = db.relationship("Buyer")
