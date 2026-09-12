import logging

from flask.views import MethodView
from flask_login import current_user, login_required
from flask_smorest import Blueprint, abort

from app.libs.decorators import buyer_required
from app.libs.errors import APIError
from app.libs.session import read_scope

from .models import ServiceCity, ServiceZone
from .schemas import (
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
            zone = ServiceabilityService.zone_for_point(
                session, args["latitude"], args["longitude"]
            )
            if zone is None:
                return {"serviceable": False, "city": None, "zone": None}
            return {
                "serviceable": True,
                "city": zone.city.name if zone.city else None,
                "zone": zone.name,
            }


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
