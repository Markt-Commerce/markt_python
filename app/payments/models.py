from enum import Enum
from external.database import db
from app.libs.models import BaseModel
from app.libs.helpers import UniqueIdMixin


class PaymentStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class PaymentMethod(Enum):
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    MOBILE_MONEY = "mobile_money"
    WALLET = "wallet"


class Payment(BaseModel, UniqueIdMixin):
    __tablename__ = "payments"
    id_prefix = "PAY_"

    # Single source of truth for legal status transitions, used by every code
    # path that moves a payment forward (webhook, browser callback, bank
    # transfer polling, cancellation/return refunds). FAILED->COMPLETED is
    # allowed because Paystack's webhook delivery isn't ordered -- a late
    # success can arrive after a local timeout already marked the payment
    # failed, and the money did land, so the payment should be rescued rather
    # than left stuck. COMPLETED->FAILED is deliberately NOT allowed: a
    # captured payment must never be flipped to failed by a late/duplicate
    # webhook. PARTIALLY_REFUNDED isn't reachable yet -- nothing sets it.
    VALID_STATUS_TRANSITIONS = {
        PaymentStatus.PENDING: [PaymentStatus.COMPLETED, PaymentStatus.FAILED],
        PaymentStatus.FAILED: [PaymentStatus.COMPLETED],
        PaymentStatus.COMPLETED: [PaymentStatus.REFUNDED],
    }

    id = db.Column(db.String(12), primary_key=True, default=None)
    order_id = db.Column(db.String(12), db.ForeignKey("orders.id"))
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default="USD")
    method = db.Column(db.Enum(PaymentMethod))
    status = db.Column(db.Enum(PaymentStatus), default=PaymentStatus.PENDING)
    transaction_id = db.Column(db.String(100))
    gateway_response = db.Column(db.JSON)
    paid_at = db.Column(db.DateTime)
    idempotency_key = db.Column(
        db.String(100), unique=True, nullable=True
    )  # Prevent duplicate payments

    order = db.relationship("Order", back_populates="payments")

    def transition_to(self, new_status: "PaymentStatus") -> None:
        """Apply a status change, raising ValueError if it isn't a legal transition."""
        allowed = Payment.VALID_STATUS_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(f"Cannot transition from {self.status} to {new_status}")
        self.status = new_status


class Transaction(BaseModel):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    seller_id = db.Column(db.Integer, db.ForeignKey("sellers.id"), nullable=True)
    amount = db.Column(db.Float)
    type = db.Column(db.String(20))  # 'credit', 'debit'
    reference = db.Column(db.String(100))
    status = db.Column(db.String(20))
    payment_metadata = db.Column(db.JSON)

    user = db.relationship("User", back_populates="transactions")
    seller = db.relationship("Seller", back_populates="transactions")
