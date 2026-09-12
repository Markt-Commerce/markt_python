import hashlib
import hmac
import logging
from datetime import datetime

from decouple import config
from flask import request
from flask.views import MethodView
from flask_login import current_user, login_required
from flask_smorest import Blueprint, abort

from app.libs.decorators import buyer_required
from app.libs.errors import APIError
from app.libs.session import read_scope, session_scope

from .models import ServiceCity, ServiceZone
from .logistics import apply_status
from .order_delivery import OrderDelivery
from .schemas import (
    JobStatusAckSchema,
    JobStatusUpdateSchema,
    QuoteRequestSchema,
    QuoteSchema,
    ServiceabilityQuerySchema,
    ServiceabilityResultSchema,
)
from .services import NotServiceable, QuoteService, ServiceabilityService

logger = logging.getLogger(__name__)

bp = Blueprint(
    "delivery",
    __name__,
    description="Delivery serviceability and quoting",
    url_prefix="/delivery",
)


@bp.route("/serviceable")
class ServiceableCheck(MethodView):
    @bp.arguments(ServiceabilityQuerySchema, location="query")
    @bp.response(200, ServiceabilityResultSchema)
    def get(self, args):
        """Whether we deliver to a point at all.

        Unauthenticated on purpose: someone deciding whether Markt is worth
        signing up for should be able to find out if we reach them.
        """
        with read_scope() as session:
            return ServiceabilityService.serviceable_summary(
                session, args["latitude"], args["longitude"]
            )


@bp.route("/quote")
class CreateQuote(MethodView):
    @login_required
    @buyer_required
    @bp.arguments(QuoteRequestSchema)
    @bp.response(201, QuoteSchema)
    @bp.alt_response(422, description="Not serviceable")
    def post(self, data):
        """Price a delivery from one seller to the buyer's chosen point."""
        from app.users.models import Seller

        with read_scope() as session:
            seller = session.query(Seller).get(data["seller_id"])
            if seller is None:
                abort(404, message="Shop not found")
            pickup = (seller.shop_latitude, seller.shop_longitude)

        try:
            quote = QuoteService.create(
                buyer_id=current_user.buyer_account.id,
                pickup=pickup,
                dropoff=(data["dropoff_latitude"], data["dropoff_longitude"]),
                seller_id=data["seller_id"],
                item_count=data["item_count"],
                total_weight_grams=data["total_weight_grams"],
                precision=data["precision"],
            )
        except NotServiceable as e:
            # Raised, not aborted: flask-smorest's abort keeps only
            # message/errors and drops the payload, which is where the reason
            # the client needs to branch on lives.
            raise
        except APIError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("Delivery quote failed")
            abort(500, message="Could not price this delivery right now.")

        return quote


def _signature_is_valid(raw_body: bytes, signature: str) -> bool:
    """HMAC-SHA512 over the raw body, hex, compared in constant time.

    Same shape as the Paystack webhook verifier this codebase already has, on
    purpose -- one way of doing this rather than two.

    No secret configured means no partner is sending us anything yet, and we
    refuse rather than accept. An unauthenticated endpoint that moves parcels
    through their delivery states is worth more to an attacker than it is to
    us.
    """
    secret = config("LOGISTICS_WEBHOOK_SECRET", default="")
    if not secret or not signature or not raw_body:
        return False
    computed = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature)


@bp.route("/jobs/<job_id>/status")
class JobStatusWebhook(MethodView):
    @bp.arguments(JobStatusUpdateSchema)
    @bp.response(200, JobStatusAckSchema)
    def post(self, data, job_id):
        """A logistics provider reporting that a parcel moved.

        Answers 200 to almost everything, deliberately. A duplicate, a status
        we do not recognise, an update that arrives out of order, even a job
        id we cannot place -- none of those are conditions the sender can fix
        by trying again, and returning 5xx at them just turns a retry policy
        into a stampede. What did or did not happen is in `applied`.

        The exception is a bad signature, which is not a delivery report at
        all.
        """
        if not _signature_is_valid(
            request.get_data(), request.headers.get("X-Markt-Signature", "")
        ):
            logger.warning("Rejected an unsigned delivery status for job %s", job_id)
            abort(401, message="Invalid signature")

        with session_scope() as session:
            delivery = (
                session.query(OrderDelivery)
                .filter_by(external_job_id=job_id)
                .with_for_update()
                .first()
            )
            if delivery is None:
                logger.warning("Delivery status for unknown job %s", job_id)
                return {"applied": False, "state": None}

            applied = apply_status(delivery, data["status"], reason=data.get("reason"))
            if applied:
                delivery.last_status_at = data.get("occurred_at") or datetime.utcnow()
            return {"applied": applied, "state": delivery.state.value}
