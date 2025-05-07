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

    id = db.Column(db.String(12), primary_key=True, default=None)
    order_id = db.Column(db.String(12), db.ForeignKey("orders.id"))
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default="USD")
    method = db.Column(db.Enum(PaymentMethod))
    status = db.Column(db.Enum(PaymentStatus), default=PaymentStatus.PENDING)
    transaction_id = db.Column(db.String(100))
    gateway_response = db.Column(db.JSON)
    paid_at = db.Column(db.DateTime)

    order = db.relationship("Order", back_populates="payments")


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
