from enum import Enum

from external.database import db
from app.libs.money import MONEY
from app.libs.models import BaseModel
from app.libs.helpers import UniqueIdMixin


class WalletEntryType(Enum):
    CREDIT = "credit"
    DEBIT = "debit"


class WalletReferenceType(Enum):
    ORDER_SETTLEMENT = "order_settlement"
    ORDER_REFUND = "order_refund"
    ORDER_PAYMENT = "order_payment"
    WALLET_TOPUP = "wallet_topup"
    WITHDRAWAL = "withdrawal"
    ADJUSTMENT = "adjustment"
    # Credited to a rider's wallet on delivery confirmation -- see
    # WalletService.credit_delivery_earning.
    DELIVERY_EARNING = "delivery_earning"


class TopUpStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class WithdrawalStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class WalletAccount(BaseModel):
    __tablename__ = "wallet_accounts"

    id = db.Column(db.Integer, primary_key=True)
    # Exactly one of user_id/delivery_user_id is set (enforced by
    # ck_wallet_accounts_single_owner) -- DeliveryUser is a structurally
    # separate table from User (delivery_users vs users), so a rider's
    # wallet can't reuse the user_id FK. See REFACTOR_NOTES.md
    # (markt_logistics), "No rider payout functionality" (2026-09-17).
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=True)
    delivery_user_id = db.Column(
        db.String(12), db.ForeignKey("delivery_users.id"), nullable=True
    )
    currency = db.Column(db.String(3), default="NGN", nullable=False)
    available_balance = db.Column(MONEY, default=0.0, nullable=False)

    user = db.relationship("User", back_populates="wallet_accounts")
    delivery_user = db.relationship("DeliveryUser")
    entries = db.relationship(
        "WalletEntry", back_populates="wallet_account", lazy="dynamic"
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "currency", name="uq_wallet_user_currency"),
        db.UniqueConstraint(
            "delivery_user_id", "currency", name="uq_wallet_delivery_user_currency"
        ),
        db.CheckConstraint(
            "(user_id IS NOT NULL) <> (delivery_user_id IS NOT NULL)",
            name="ck_wallet_accounts_single_owner",
        ),
    )


class WalletEntry(BaseModel):
    __tablename__ = "wallet_entries"

    id = db.Column(db.Integer, primary_key=True)
    wallet_account_id = db.Column(
        db.Integer, db.ForeignKey("wallet_accounts.id"), nullable=False
    )
    entry_type = db.Column(db.Enum(WalletEntryType), nullable=False)
    amount = db.Column(MONEY, nullable=False)
    balance_after = db.Column(MONEY, nullable=False)
    reference_type = db.Column(db.Enum(WalletReferenceType), nullable=False)
    reference_id = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255))
    idempotency_key = db.Column(db.String(100), unique=True, nullable=True)

    wallet_account = db.relationship("WalletAccount", back_populates="entries")


class WithdrawalRequest(BaseModel, UniqueIdMixin):
    __tablename__ = "withdrawal_requests"
    id_prefix = "WDR_"

    id = db.Column(db.String(12), primary_key=True, default=None)
    # Same single-owner rule as WalletAccount above.
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=True)
    delivery_user_id = db.Column(
        db.String(12), db.ForeignKey("delivery_users.id"), nullable=True
    )
    amount = db.Column(MONEY, nullable=False)
    currency = db.Column(db.String(3), default="NGN", nullable=False)
    bank_code = db.Column(db.String(10), nullable=False)
    account_number = db.Column(db.String(20), nullable=False)
    account_name = db.Column(db.String(100), nullable=False)
    status = db.Column(
        db.Enum(WithdrawalStatus), default=WithdrawalStatus.PENDING, nullable=False
    )
    paystack_transfer_ref = db.Column(db.String(100), nullable=True)
    failure_reason = db.Column(db.String(255), nullable=True)

    user = db.relationship("User", back_populates="withdrawal_requests")
    delivery_user = db.relationship("DeliveryUser")

    __table_args__ = (
        db.CheckConstraint(
            "(user_id IS NOT NULL) <> (delivery_user_id IS NOT NULL)",
            name="ck_withdrawal_requests_single_owner",
        ),
    )

    @property
    def owner_id(self) -> str:
        """The id of whoever this withdrawal belongs to, regardless of
        which FK is populated -- use this instead of `.user_id` directly
        whenever the row might belong to a delivery partner."""
        return self.user_id or self.delivery_user_id


class WalletTopUp(BaseModel, UniqueIdMixin):
    __tablename__ = "wallet_topups"
    id_prefix = "TOP_"

    id = db.Column(db.String(12), primary_key=True, default=None)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=False)
    amount = db.Column(MONEY, nullable=False)
    currency = db.Column(db.String(3), default="NGN", nullable=False)
    status = db.Column(
        db.Enum(TopUpStatus), default=TopUpStatus.PENDING, nullable=False
    )
    paystack_reference = db.Column(db.String(100), unique=True, nullable=True)

    user = db.relationship("User", back_populates="wallet_topups")
