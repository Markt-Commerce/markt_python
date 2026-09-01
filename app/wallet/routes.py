from flask import current_app, redirect, request
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
    TopUpVerifyResponseSchema,
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


@bp.route("/topup/<topup_id>/verify")
class WalletTopUpVerify(MethodView):
    @login_required
    @bp.response(200, TopUpVerifyResponseSchema)
    def get(self, topup_id):
        """Confirm a top-up with Paystack and credit it if it succeeded.

        The client calls this once its payment webview closes. It never
        reports success itself -- this asks Paystack directly.
        """
        try:
            return WalletService.verify_topup(topup_id, user_id=current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/topup/callback/<topup_id>")
class WalletTopUpCallback(MethodView):
    def get(self, topup_id):
        """Paystack's browser redirect after a top-up.

        This is the callback_url handed to Paystack in
        WalletService.initialize_topup. It previously pointed at no route at
        all, so a user who topped up landed on a 404 and the app was never
        deep-linked back -- the balance only moved once the webhook arrived.
        """
        from main.config import settings
        from urllib.parse import urlencode

        # Echoed back by Paystack from the callback_url we set at initialize.
        platform = request.args.get("platform", "web")

        def client_redirect(status: str, **params):
            query = urlencode({k: v for k, v in params.items() if v is not None})
            if platform == "mobile":
                url = f"{settings.MOBILE_APP_SCHEME}wallet/{status}"
            else:
                url = f"{settings.WEB_APP_BASE_URL}/wallet-{status}"
            return redirect(f"{url}?{query}" if query else url)

        try:
            result = WalletService.verify_topup(topup_id)
            if result.get("verified"):
                return client_redirect(
                    "success", topup_id=topup_id, amount=result.get("amount")
                )
            return client_redirect("failed", topup_id=topup_id)
        except Exception as e:
            current_app.logger.error(
                "Wallet top-up callback failed for %s: %s", topup_id, e, exc_info=True
            )
            # Verification can fail transiently, and the webhook may already
            # have credited the wallet. Never tell a user who paid "failed"
            # on the strength of a gateway timeout -- re-read local state.
            try:
                from .models import TopUpStatus
                from app.libs.session import session_scope
                from .models import WalletTopUp

                with session_scope() as session:
                    topup = session.query(WalletTopUp).get(topup_id)
                    if topup and topup.status == TopUpStatus.COMPLETED:
                        return client_redirect("success", topup_id=topup_id)
            except Exception:
                pass
            return client_redirect("failed", topup_id=topup_id, error="server_error")


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
