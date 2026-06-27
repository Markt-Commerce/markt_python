from flask.views import MethodView
from flask_login import current_user, login_required
from flask_smorest import Blueprint, abort

from app.libs.errors import APIError
from app.libs.schemas import PaginationQueryArgs

from .schemas import (
    WalletBalanceSchema,
    WalletTransactionsResponseSchema,
    WithdrawalRequestSchema,
    WithdrawalResponseSchema,
    WithdrawalListResponseSchema,
    TopUpInitializeSchema,
    TopUpInitializeResponseSchema,
    SellerPayoutAccountSchema,
    SellerPayoutAccountResponseSchema,
)
from .services import WalletService

bp = Blueprint(
    "wallet", __name__, description="User wallet operations", url_prefix="/wallet"
)


@bp.route("/")
class WalletBalance(MethodView):
    @login_required
    @bp.response(200, WalletBalanceSchema)
    def get(self):
        """Get current user's wallet balance"""
        try:
            return WalletService.get_balance(current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/transactions")
class WalletTransactions(MethodView):
    @login_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, WalletTransactionsResponseSchema)
    def get(self, args):
        """List wallet transaction history"""
        try:
            return WalletService.list_transactions(
                current_user.id,
                page=args.get("page", 1),
                per_page=args.get("per_page", 20),
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/withdraw")
class WalletWithdraw(MethodView):
    @login_required
    @bp.arguments(WithdrawalRequestSchema)
    @bp.response(201, WithdrawalResponseSchema)
    def post(self, data):
        """Request a withdrawal to a bank account via Paystack transfer"""
        try:
            withdrawal = WalletService.request_withdrawal(current_user.id, data)
            return withdrawal
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/withdrawals")
class WalletWithdrawals(MethodView):
    @login_required
    @bp.arguments(PaginationQueryArgs, location="query")
    @bp.response(200, WithdrawalListResponseSchema)
    def get(self, args):
        """List withdrawal requests for the current user"""
        try:
            return WalletService.list_withdrawals(
                current_user.id,
                page=args.get("page", 1),
                per_page=args.get("per_page", 20),
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/topup/initialize")
class WalletTopUpInitialize(MethodView):
    @login_required
    @bp.arguments(TopUpInitializeSchema)
    @bp.response(201, TopUpInitializeResponseSchema)
    def post(self, data):
        """Initialize a Paystack wallet top-up"""
        try:
            return WalletService.initialize_topup(
                current_user.id,
                data["amount"],
                currency=data.get("currency", "NGN"),
                platform=data.get("platform", "web"),
            )
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/seller/payout-account")
class SellerPayoutAccount(MethodView):
    @login_required
    @bp.arguments(SellerPayoutAccountSchema)
    @bp.response(201, SellerPayoutAccountResponseSchema)
    def post(self, data):
        """Register seller bank account for Paystack split settlements"""
        try:
            if not current_user.is_seller or not current_user.seller_account:
                abort(403, message="Seller account required")
            return WalletService.register_seller_payout_account(
                current_user.seller_account.id,
                bank_code=data["bank_code"],
                account_number=data["account_number"],
                account_name=data["account_name"],
            )
        except APIError as e:
            abort(e.status_code, message=e.message)
