import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError

from app.libs.errors import APIError, NotFoundError, ValidationError, ConflictError
from app.libs.session import session_scope
from app.orders.models import OrderItem

from .models import (
    WalletAccount,
    WalletEntry,
    WalletEntryType,
    WalletReferenceType,
    WalletTopUp,
    TopUpStatus,
    WithdrawalRequest,
    WithdrawalStatus,
)
from .paystack_transfers import PaystackTransferClient
from .paystack_subaccounts import PaystackSubaccountClient

logger = logging.getLogger(__name__)

# Sellers keep 100% of item price for now — Markt earns only via the buyer-facing
# service fee, not a seller-side commission.
DEFAULT_COMMISSION_RATE = 0.0
MIN_WITHDRAWAL_AMOUNT = 1000.0


class WalletService:
    @staticmethod
    def _get_or_create_account(
        session, user_id: str, currency: str = "NGN", *, for_update: bool = False
    ) -> WalletAccount:
        """Fetch (or open) a user's wallet.

        `for_update` takes a row lock, which every balance mutation must hold --
        see the note in `credit`.
        """

        def _query():
            q = session.query(WalletAccount).filter_by(
                user_id=user_id, currency=currency
            )
            return q.with_for_update() if for_update else q

        account = _query().first()
        if account:
            return account

        # Two requests can open the same wallet at the same moment. The
        # (user_id, currency) unique constraint decides which insert wins; the
        # loser rolls back to the savepoint and re-reads the winner's row
        # rather than failing the whole enclosing transaction.
        savepoint = session.begin_nested()
        try:
            account = WalletAccount(
                user_id=user_id, currency=currency, available_balance=0.0
            )
            session.add(account)
            savepoint.commit()
            return account
        except IntegrityError:
            savepoint.rollback()
            return _query().one()

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
                        "created_at": (
                            entry.created_at.isoformat() if entry.created_at else None
                        ),
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
            # Lock the wallet row BEFORE the idempotency check. Two things
            # depend on that ordering:
            #  1. The balance read-modify-write below is not atomic on its own.
            #     Paystack retries a webhook every 3 minutes (4 times, then
            #     hourly for 72h), so concurrent deliveries of the same event
            #     were genuinely able to interleave and lose a credit.
            #  2. It makes the check-then-insert on idempotency_key atomic per
            #     wallet, so a retry can't slip past the SELECT and then fail
            #     on the unique constraint.
            account = WalletService._get_or_create_account(
                session, user_id, currency, for_update=True
            )

            if idempotency_key:
                existing = (
                    session.query(WalletEntry)
                    .filter_by(idempotency_key=idempotency_key)
                    .first()
                )
                if existing:
                    return existing

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
            # Lock first -- see `credit`. This is what stops two concurrent
            # withdrawals from each passing the balance check below and
            # together overdrawing the wallet.
            account = WalletService._get_or_create_account(
                session, user_id, currency, for_update=True
            )

            if idempotency_key:
                existing = (
                    session.query(WalletEntry)
                    .filter_by(idempotency_key=idempotency_key)
                    .first()
                )
                if existing:
                    return existing

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
        from app.orders.models import Order

        with session_scope() as session:
            order = session.query(Order).get(order_item.order_id)
            if order and order.paystack_split_used:
                return None

        if not order_item.seller or not order_item.seller.user_id:
            return None

        gross = (order_item.price or 0) * (order_item.quantity or 0)
        if gross <= 0:
            return None

        if not 0 <= commission_rate <= 1:
            raise ValidationError(f"Invalid commission rate: {commission_rate}")

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
    def refund_order_item_to_wallet(
        buyer_user_id: str,
        order_item_id: int,
        amount: float,
        reason: Optional[str] = None,
    ) -> WalletEntry:
        """11.8: refund a single unfulfillable item -- see
        OrderService.refund_unresolved_item. Same ORDER_REFUND reference
        type as the whole-order refund above, just keyed by item id
        instead of order id -- OrderService._get_total_refunded sums both
        together per order so the escrow invariant stays cumulative-aware
        regardless of which granularity a given refund was issued at."""
        description = f"Refund for unfulfilled order item {order_item_id}"
        if reason:
            description += f": {reason}"
        return WalletService.credit(
            buyer_user_id,
            amount,
            WalletReferenceType.ORDER_REFUND,
            str(order_item_id),
            description=description,
            idempotency_key=f"refund:item:{order_item_id}",
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

        # The balance check above ran in its own committed transaction, so a
        # concurrent withdrawal can still take the money before this debit
        # lands (the debit re-checks under a row lock and raises). Without this
        # cleanup the request row stayed PENDING forever: shown to the user as
        # an in-flight withdrawal, and a candidate for any future sweeper to
        # pay out money that was never debited.
        try:
            WalletService.debit(
                user_id,
                amount,
                WalletReferenceType.WITHDRAWAL,
                withdrawal_id,
                description="Withdrawal request",
                idempotency_key=f"withdraw:{withdrawal_id}",
                currency=currency,
            )
        except APIError:
            with session_scope() as session:
                orphan = session.query(WithdrawalRequest).get(withdrawal_id)
                if orphan and orphan.status == WithdrawalStatus.PENDING:
                    orphan.status = WithdrawalStatus.FAILED
                    orphan.failure_reason = "Insufficient balance at debit time"
            raise

        try:
            from app.wallet.tasks import process_withdrawal

            process_withdrawal.delay(withdrawal_id)
        except Exception as exc:
            logger.warning(
                "Async withdrawal dispatch failed for %s: %s", withdrawal_id, exc
            )
            try:
                return WalletService.process_withdrawal(withdrawal_id)
            except APIError:
                pass

        with session_scope() as session:
            return session.query(WithdrawalRequest).get(withdrawal_id)

    @staticmethod
    def list_withdrawals(
        user_id: str, page: int = 1, per_page: int = 20
    ) -> Dict[str, Any]:
        with session_scope() as session:
            query = (
                session.query(WithdrawalRequest)
                .filter_by(user_id=user_id)
                .order_by(WithdrawalRequest.created_at.desc())
            )
            total = query.count()
            rows = query.offset((page - 1) * per_page).limit(per_page).all()
            return {
                "withdrawals": [
                    {
                        "id": row.id,
                        "amount": row.amount,
                        "currency": row.currency,
                        "status": row.status.value,
                        "account_name": row.account_name,
                        "account_number": row.account_number[-4:].rjust(
                            len(row.account_number), "*"
                        ),
                        "paystack_transfer_ref": row.paystack_transfer_ref,
                        "failure_reason": row.failure_reason,
                        "created_at": (
                            row.created_at.isoformat() if row.created_at else None
                        ),
                    }
                    for row in rows
                ],
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_items": total,
                    "total_pages": (total + per_page - 1) // per_page,
                },
            }

    @staticmethod
    def process_withdrawal(withdrawal_id: str) -> WithdrawalRequest:
        """Submit a pending withdrawal to Paystack Transfer API."""
        with session_scope() as session:
            withdrawal = session.query(WithdrawalRequest).get(withdrawal_id)
            if not withdrawal:
                raise NotFoundError("Withdrawal request not found")
            if withdrawal.status != WithdrawalStatus.PENDING:
                return withdrawal

            withdrawal.status = WithdrawalStatus.PROCESSING
            session.flush()

            amount = withdrawal.amount
            bank_code = withdrawal.bank_code
            account_number = withdrawal.account_number
            account_name = withdrawal.account_name
            currency = withdrawal.currency
            user_id = withdrawal.user_id

        try:
            recipient_code = PaystackTransferClient.create_transfer_recipient(
                account_name=account_name,
                account_number=account_number,
                bank_code=bank_code,
                currency=currency,
            )
            transfer_data = PaystackTransferClient.initiate_transfer(
                amount_kobo=int(round(amount * 100)),
                recipient_code=recipient_code,
                reference=withdrawal_id,
            )
            transfer_ref = transfer_data.get("data", {}).get("reference", withdrawal_id)

            with session_scope() as session:
                withdrawal = session.query(WithdrawalRequest).get(withdrawal_id)
                withdrawal.paystack_transfer_ref = transfer_ref
                session.flush()
                return withdrawal

        except APIError as exc:
            WalletService._fail_withdrawal(
                withdrawal_id, user_id, amount, currency, str(exc.message)
            )
            raise

    @staticmethod
    def _fail_withdrawal(
        withdrawal_id: str,
        user_id: str,
        amount: float,
        currency: str,
        reason: str,
    ):
        """Mark withdrawal failed and refund debited amount to wallet."""
        WalletService.credit(
            user_id,
            amount,
            WalletReferenceType.ADJUSTMENT,
            withdrawal_id,
            description=f"Withdrawal failed: {reason}",
            idempotency_key=f"withdraw-refund:{withdrawal_id}",
            currency=currency,
        )
        with session_scope() as session:
            withdrawal = session.query(WithdrawalRequest).get(withdrawal_id)
            if withdrawal:
                withdrawal.status = WithdrawalStatus.FAILED
                withdrawal.failure_reason = reason[:255]

    @staticmethod
    def complete_withdrawal_transfer(reference: str) -> bool:
        with session_scope() as session:
            withdrawal = (
                session.query(WithdrawalRequest)
                .filter(
                    (WithdrawalRequest.id == reference)
                    | (WithdrawalRequest.paystack_transfer_ref == reference)
                )
                .first()
            )
            if not withdrawal:
                logger.warning("Withdrawal not found for transfer ref %s", reference)
                return False
            if withdrawal.status == WithdrawalStatus.COMPLETED:
                return True
            withdrawal.status = WithdrawalStatus.COMPLETED
            return True

    @staticmethod
    def fail_withdrawal_transfer(reference: str, reason: str = "") -> bool:
        with session_scope() as session:
            withdrawal = (
                session.query(WithdrawalRequest)
                .filter(
                    (WithdrawalRequest.id == reference)
                    | (WithdrawalRequest.paystack_transfer_ref == reference)
                )
                .first()
            )
            if not withdrawal:
                return False
            if withdrawal.status == WithdrawalStatus.FAILED:
                return True

            user_id = withdrawal.user_id
            amount = withdrawal.amount
            currency = withdrawal.currency
            withdrawal_id = withdrawal.id

        WalletService._fail_withdrawal(
            withdrawal_id, user_id, amount, currency, reason or "Transfer failed"
        )
        return True

    @staticmethod
    def pay_for_order(
        user_id: str,
        order_id: str,
        payment_id: str,
        amount: float,
        currency: str = "NGN",
    ) -> WalletEntry:
        """Debit buyer wallet for an order payment."""
        return WalletService.debit(
            user_id,
            amount,
            WalletReferenceType.ORDER_PAYMENT,
            payment_id,
            description=f"Wallet payment for order {order_id}",
            idempotency_key=f"pay:wallet:{payment_id}",
            currency=currency,
        )

    @staticmethod
    def initialize_topup(
        user_id: str,
        amount: float,
        currency: str = "NGN",
        *,
        platform: str = "web",
    ) -> Dict[str, Any]:
        """Create a pending top-up and return Paystack authorization URL."""
        import requests
        from app.payments.services import PaymentService
        from app.users.models import User
        from main.config import settings

        if amount < 100:
            raise ValidationError("Minimum top-up amount is 100")

        topup_id = None
        with session_scope() as session:
            user = session.query(User).get(user_id)
            if not user:
                raise NotFoundError("User not found")

            topup = WalletTopUp(
                user_id=user_id,
                amount=round(amount, 2),
                currency=currency,
                status=TopUpStatus.PENDING,
            )
            session.add(topup)
            session.flush()
            topup_id = topup.id
            user_email = user.email

        reference = f"TOP_{topup_id}"
        base_url = settings.API_BASE_URL or "http://localhost:8000"
        callback_url = (
            f"{base_url}/api/v1/wallet/topup/callback/{topup_id}"
            f"?platform={platform}"
        )

        payload = {
            "amount": int(round(amount * 100)),
            "email": user_email,
            "currency": currency,
            "reference": reference,
            "callback_url": callback_url,
            "metadata": {
                "type": "wallet_topup",
                "topup_id": topup_id,
                "user_id": user_id,
            },
        }

        response = requests.post(
            f"{PaymentService.PAYSTACK_BASE_URL}/transaction/initialize",
            json=payload,
            headers={"Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"},
            timeout=30,
        )
        data = response.json()
        if response.status_code != 200 or not data.get("status"):
            with session_scope() as session:
                topup = session.query(WalletTopUp).get(topup_id)
                if topup:
                    topup.status = TopUpStatus.FAILED
            raise APIError("Failed to initialize wallet top-up", 502)

        auth_url = data["data"]["authorization_url"]
        paystack_ref = data["data"]["reference"]

        with session_scope() as session:
            topup = session.query(WalletTopUp).get(topup_id)
            topup.paystack_reference = paystack_ref
            session.flush()

        return {
            "topup_id": topup_id,
            "amount": amount,
            "currency": currency,
            "authorization_url": auth_url,
            "reference": paystack_ref,
        }

    @staticmethod
    def complete_topup(
        reference: str, gateway_response: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Idempotently credit wallet after successful Paystack top-up."""
        topup_id = (
            reference.replace("TOP_", "", 1) if reference.startswith("TOP_") else None
        )

        with session_scope() as session:
            if topup_id:
                topup = session.query(WalletTopUp).get(topup_id)
            else:
                topup = (
                    session.query(WalletTopUp)
                    .filter_by(paystack_reference=reference)
                    .first()
                )

            if not topup:
                logger.warning("Top-up not found for reference %s", reference)
                return False

            if topup.status == TopUpStatus.COMPLETED:
                return True

            # Never credit on the strength of the event name alone. Paystack's
            # own guidance is to confirm data.status, data.amount and
            # data.currency against what was expected before giving value --
            # the webhook body is attacker-shaped input right up until the
            # signature check, and a signed-but-stale event can still carry an
            # amount that doesn't match this top-up.
            if gateway_response is not None:
                expected_kobo = int(round(topup.amount * 100))
                paid_status = gateway_response.get("status")
                paid_kobo = gateway_response.get("amount")
                paid_currency = gateway_response.get("currency")

                if paid_status is not None and paid_status != "success":
                    logger.warning(
                        "Top-up %s not credited: gateway status is %s",
                        topup.id,
                        paid_status,
                    )
                    return False
                if paid_kobo is not None and int(paid_kobo) != expected_kobo:
                    logger.error(
                        "Top-up %s amount mismatch: expected %s kobo, gateway "
                        "reported %s kobo -- refusing to credit",
                        topup.id,
                        expected_kobo,
                        paid_kobo,
                    )
                    return False
                if paid_currency is not None and paid_currency != topup.currency:
                    logger.error(
                        "Top-up %s currency mismatch: expected %s, gateway "
                        "reported %s -- refusing to credit",
                        topup.id,
                        topup.currency,
                        paid_currency,
                    )
                    return False

            user_id = topup.user_id
            amount = topup.amount
            currency = topup.currency
            topup_ref = topup.id
            topup.status = TopUpStatus.COMPLETED
            session.flush()

        WalletService.credit(
            user_id,
            amount,
            WalletReferenceType.WALLET_TOPUP,
            topup_ref,
            description=f"Wallet top-up {topup_ref}",
            idempotency_key=f"topup:{topup_ref}",
            currency=currency,
        )
        return True

    @staticmethod
    def verify_topup(topup_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Confirm a top-up directly with Paystack and credit it if it landed.

        The webhook is the primary path, but it is asynchronous and can be
        delayed or lost. This gives the client (and the browser callback) a
        synchronous server-side confirmation instead of trusting whatever the
        redirect claims -- the client is never the authority on payment.
        """
        import requests
        from app.payments.services import PaymentService

        with session_scope() as session:
            topup = session.query(WalletTopUp).get(topup_id)
            if not topup:
                raise NotFoundError("Top-up not found")
            if user_id and topup.user_id != user_id:
                raise NotFoundError("Top-up not found")

            if topup.status == TopUpStatus.COMPLETED:
                return {
                    "topup_id": topup.id,
                    "status": TopUpStatus.COMPLETED.value,
                    "verified": True,
                    "amount": topup.amount,
                    "currency": topup.currency,
                }

            reference = topup.paystack_reference
            amount = topup.amount
            currency = topup.currency

        if not reference:
            raise ValidationError("No Paystack reference to verify")

        try:
            response = requests.get(
                f"{PaymentService.PAYSTACK_BASE_URL}/transaction/verify/{reference}",
                headers={
                    "Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"
                },
                timeout=20,
            )
            body = response.json()
        except Exception:
            logger.exception(
                "Paystack verification call failed for top-up %s", topup_id
            )
            raise APIError("Could not verify top-up with Paystack", 502)

        # `status` is whether the API call worked; `data.status` is whether the
        # money actually moved. Both have to be right.
        gateway_data = (body or {}).get("data") or {}
        if response.status_code != 200 or not body.get("status"):
            raise APIError("Could not verify top-up with Paystack", 502)

        if gateway_data.get("status") == "success":
            credited = WalletService.complete_topup(reference, gateway_data)
            return {
                "topup_id": topup_id,
                "status": (
                    TopUpStatus.COMPLETED.value
                    if credited
                    else TopUpStatus.PENDING.value
                ),
                "verified": credited,
                "amount": amount,
                "currency": currency,
            }

        # Paystack reports "failed" or "abandoned" as terminal; anything else
        # (e.g. "ongoing") stays pending so the webhook can still settle it.
        if gateway_data.get("status") in ("failed", "abandoned", "reversed"):
            with session_scope() as session:
                topup = session.query(WalletTopUp).get(topup_id)
                if topup and topup.status == TopUpStatus.PENDING:
                    topup.status = TopUpStatus.FAILED

        return {
            "topup_id": topup_id,
            "status": (gateway_data.get("status") or TopUpStatus.PENDING.value),
            "verified": False,
            "amount": amount,
            "currency": currency,
        }

    @staticmethod
    def register_seller_payout_account(
        seller_id: int,
        *,
        bank_code: str,
        account_number: str,
        account_name: str,
    ) -> Dict[str, Any]:
        """Register seller bank details and create Paystack subaccount."""
        from app.users.models import Seller
        from main.config import settings

        with session_scope() as session:
            seller = session.query(Seller).get(seller_id)
            if not seller:
                raise NotFoundError("Seller not found")
            if seller.paystack_subaccount_code:
                raise ConflictError("Seller payout account already registered")

            shop_name = seller.shop_name or f"Seller {seller_id}"
            commission_pct = round(settings.PLATFORM_COMMISSION_RATE * 100, 2)

        subaccount = PaystackSubaccountClient.create_subaccount(
            business_name=shop_name,
            bank_code=bank_code,
            account_number=account_number,
            percentage_charge=commission_pct,
        )

        with session_scope() as session:
            seller = session.query(Seller).get(seller_id)
            seller.paystack_subaccount_code = subaccount["subaccount_code"]
            seller.payout_bank_code = bank_code
            seller.payout_account_number = account_number
            seller.payout_account_name = account_name
            session.flush()
            return {
                "seller_id": seller.id,
                "subaccount_code": seller.paystack_subaccount_code,
                "account_name": seller.payout_account_name,
                "account_number_masked": account_number[-4:].rjust(
                    len(account_number), "*"
                ),
            }
