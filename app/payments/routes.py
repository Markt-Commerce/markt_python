# package imports
from flask_smorest import Blueprint
from flask.views import MethodView
from flask_login import login_required, current_user


bp = Blueprint(
    "payments", __name__, description="Payment operations", url_prefix="/payments"
)

# TODOs:
@bp.route("/methods")
class PaymentMethods(MethodView):
    # TODO: List available payment methods
    # TODO: Save payment methods
    # TODO: Default payment method
    def get(self):
        pass


@bp.route("/process")
class PaymentProcessing(MethodView):
    # TODO: Handle payment intents
    # TODO: 3D Secure flow
    # TODO: Webhook for payment providers
    def post(self):
        pass
