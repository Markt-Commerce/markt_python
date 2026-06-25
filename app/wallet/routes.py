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
        """Request a withdrawal to a bank account (queued for Paystack transfer)"""
        try:
            withdrawal = WalletService.request_withdrawal(current_user.id, data)
            return withdrawal
        except APIError as e:
            abort(e.status_code, message=e.message)
