import logging
import uuid
from typing import Any, Dict, Optional

from app.libs.errors import ValidationError
from app.libs.session import session_scope
from app.orders.models import OrderItem

from .models import (
    WalletAccount,
    WalletEntry,
    WalletEntryType,
    WalletReferenceType,
    WithdrawalRequest,
    WithdrawalStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_COMMISSION_RATE = 0.10
MIN_WITHDRAWAL_AMOUNT = 1000.0


class WalletService:
    @staticmethod
    def _get_or_create_account(
        session, user_id: str, currency: str = "NGN"
    ) -> WalletAccount:
        account = (
            session.query(WalletAccount)
            .filter_by(user_id=user_id, currency=currency)
            .first()
        )
        if not account:
            account = WalletAccount(
                user_id=user_id, currency=currency, available_balance=0.0
            )
            session.add(account)
            session.flush()
        return account

    @staticmethod
    def get_balance(user_id: str, currency: str = "NGN") -> Dict[str, Any]:
        with session_scope() as session:
            account = WalletService._get_or_create_account(session, user_id, currency)
            return {
                "currency": account.currency,
                "available_balance": round(account.available_balance, 2),
            }

    @staticmethod
    def list_transactions(
        user_id: str, page: int = 1, per_page: int = 20
    ) -> Dict[str, Any]:
        with session_scope() as session:
            account = WalletService._get_or_create_account(session, user_id)
            query = (
                session.query(WalletEntry)
                .filter_by(wallet_account_id=account.id)
                .order_by(WalletEntry.created_at.desc())
            )
            total = query.count()
            entries = query.offset((page - 1) * per_page).limit(per_page).all()
            return {
                "transactions": [
                    {
                        "id": entry.id,
                        "type": entry.entry_type.value,
                        "amount": entry.amount,
                        "balance_after": entry.balance_after,
                        "reference_type": entry.reference_type.value,
                        "reference_id": entry.reference_id,
                        "description": entry.description,
                        "created_at": entry.created_at.isoformat()
                        if entry.created_at
                        else None,
                    }
                    for entry in entries
                ],
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_items": total,
                    "total_pages": (total + per_page - 1) // per_page,
                },
            }

    @staticmethod
    def credit(
        user_id: str,
        amount: float,
        reference_type: WalletReferenceType,
        reference_id: str,
        *,
        description: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        currency: str = "NGN",
    ) -> WalletEntry:
        if amount <= 0:
            raise ValidationError("Credit amount must be positive")

        with session_scope() as session:
            if idempotency_key:
                existing = (
                    session.query(WalletEntry)
                    .filter_by(idempotency_key=idempotency_key)
                    .first()
                )
                if existing:
                    return existing

            account = WalletService._get_or_create_account(session, user_id, currency)
            account.available_balance = round(account.available_balance + amount, 2)
            entry = WalletEntry(
                wallet_account_id=account.id,
                entry_type=WalletEntryType.CREDIT,
                amount=round(amount, 2),
                balance_after=account.available_balance,
                reference_type=reference_type,
                reference_id=reference_id,
                description=description,
                idempotency_key=idempotency_key or str(uuid.uuid4()),
            )
            session.add(entry)
            session.flush()
            return entry

    @staticmethod
    def debit(
        user_id: str,
        amount: float,
        reference_type: WalletReferenceType,
        reference_id: str,
        *,
        description: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        currency: str = "NGN",
    ) -> WalletEntry:
        if amount <= 0:
            raise ValidationError("Debit amount must be positive")

        with session_scope() as session:
            if idempotency_key:
                existing = (
                    session.query(WalletEntry)
                    .filter_by(idempotency_key=idempotency_key)
                    .first()
                )
                if existing:
                    return existing

            account = WalletService._get_or_create_account(session, user_id, currency)
            if account.available_balance < amount:
                raise ValidationError("Insufficient wallet balance")

            account.available_balance = round(account.available_balance - amount, 2)
            entry = WalletEntry(
                wallet_account_id=account.id,
                entry_type=WalletEntryType.DEBIT,
                amount=round(amount, 2),
                balance_after=account.available_balance,
                reference_type=reference_type,
                reference_id=reference_id,
                description=description,
                idempotency_key=idempotency_key or str(uuid.uuid4()),
            )
            session.add(entry)
            session.flush()
            return entry

    @staticmethod
    def settle_order_item(
        order_item: OrderItem, commission_rate: float = DEFAULT_COMMISSION_RATE
    ) -> Optional[WalletEntry]:
        """Credit seller wallet when an order item is delivered."""
        if not order_item.seller or not order_item.seller.user_id:
            return None

        gross = (order_item.price or 0) * (order_item.quantity or 0)
        if gross <= 0:
            return None

        net = round(gross * (1 - commission_rate), 2)
        if net <= 0:
            return None

        return WalletService.credit(
            order_item.seller.user_id,
            net,
            WalletReferenceType.ORDER_SETTLEMENT,
            str(order_item.id),
            description=f"Settlement for order item {order_item.id}",
            idempotency_key=f"settle:item:{order_item.id}",
        )

    @staticmethod
    def refund_order_to_wallet(
        buyer_user_id: str,
        order_id: str,
        amount: float,
    ) -> WalletEntry:
        return WalletService.credit(
            buyer_user_id,
            amount,
            WalletReferenceType.ORDER_REFUND,
            order_id,
            description=f"Refund for cancelled order {order_id}",
            idempotency_key=f"refund:order:{order_id}",
        )

    @staticmethod
    def request_withdrawal(user_id: str, data: Dict[str, Any]) -> WithdrawalRequest:
        amount = float(data["amount"])
        if amount < MIN_WITHDRAWAL_AMOUNT:
            raise ValidationError(
                f"Minimum withdrawal amount is {MIN_WITHDRAWAL_AMOUNT}"
            )

        withdrawal_id = None
        currency = data.get("currency", "NGN")

        with session_scope() as session:
            account = WalletService._get_or_create_account(session, user_id, currency)
            if account.available_balance < amount:
                raise ValidationError("Insufficient wallet balance for withdrawal")

            withdrawal = WithdrawalRequest(
                user_id=user_id,
                amount=amount,
                currency=account.currency,
                bank_code=data["bank_code"],
                account_number=data["account_number"],
                account_name=data["account_name"],
                status=WithdrawalStatus.PENDING,
            )
            session.add(withdrawal)
            session.flush()
            withdrawal_id = withdrawal.id
            currency = withdrawal.currency

        WalletService.debit(
            user_id,
            amount,
            WalletReferenceType.WITHDRAWAL,
            withdrawal_id,
            description="Withdrawal request",
            idempotency_key=f"withdraw:{withdrawal_id}",
            currency=currency,
        )

        with session_scope() as session:
            return session.query(WithdrawalRequest).get(withdrawal_id)
