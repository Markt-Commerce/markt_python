import logging

from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint
from flask_login import current_user

from app.libs.session import session_scope, read_scope

from .models import BrowseLocation
from .schemas import (
    BrowseLocationSchema,
    NearbyFeedSchema,
    NearbyQueryArgs,
    SetBrowseLocationSchema,
)
from .services import scoped_products

logger = logging.getLogger(__name__)

bp = Blueprint(
    "location",
    __name__,
    description="Browse location and nearby content",
    url_prefix="/location",
)


def _identity(guest_id):
    """(user_id, guest_id) for whoever is asking.

    A signed-in user is keyed by user id so their choice follows them across
    devices; everyone else by the guest id their app generated. Never both.
    """
    if getattr(current_user, "is_authenticated", False):
        return current_user.id, None
    return None, guest_id


@bp.route("/browse")
class Browse(MethodView):
    """Where the user is looking.

    Deliberately not the shipping address: changing where you browse must never
    change where an order is delivered.
    """

    @bp.arguments(NearbyQueryArgs, location="query")
    @bp.response(200, BrowseLocationSchema)
    def get(self, args):
        user_id, guest_id = _identity(args.get("guest_id"))
        with read_scope() as session:
            q = session.query(BrowseLocation)
            row = (
                q.filter_by(user_id=user_id).first()
                if user_id
                else (q.filter_by(guest_id=guest_id).first() if guest_id else None)
            )
            if not row:
                # No location chosen yet is a normal state, not an error: the
                # app falls back to the nationwide feed and prompts.
                return {}
            return {
                "latitude": row.latitude,
                "longitude": row.longitude,
                "label": row.label,
                "state": row.state,
                "lga": row.lga,
            }

    @bp.arguments(SetBrowseLocationSchema)
    @bp.response(200, BrowseLocationSchema)
    def put(self, data):
        from datetime import datetime

        user_id, guest_id = _identity(data.get("guest_id"))
        if not user_id and not guest_id:
            # Without either key there is nothing to store it against.
            return {}

        with session_scope() as session:
            q = session.query(BrowseLocation)
            row = (
                q.filter_by(user_id=user_id).first()
                if user_id
                else q.filter_by(guest_id=guest_id).first()
            )
            if not row:
                row = BrowseLocation(user_id=user_id, guest_id=guest_id)
                session.add(row)

            row.latitude = data["latitude"]
            row.longitude = data["longitude"]
            row.label = data.get("label")
            row.state = data.get("state")
            row.lga = data.get("lga")
            row.updated_at_utc = datetime.utcnow()
            session.flush()

            return {
                "latitude": row.latitude,
                "longitude": row.longitude,
                "label": row.label,
                "state": row.state,
                "lga": row.lga,
            }


@bp.route("/nearby")
class Nearby(MethodView):
    """Products ranked by distance from a browse location.

    Public: a guest browsing before signing up is the point. Coordinates may be
    passed explicitly or taken from the stored browse location.
    """

    @bp.arguments(NearbyQueryArgs, location="query")
    @bp.response(200, NearbyFeedSchema)
    def get(self, args):
        lat, lng = args.get("latitude"), args.get("longitude")

        if lat is None or lng is None:
            user_id, guest_id = _identity(args.get("guest_id"))
            with read_scope() as session:
                q = session.query(BrowseLocation)
                row = (
                    q.filter_by(user_id=user_id).first()
                    if user_id
                    else (q.filter_by(guest_id=guest_id).first() if guest_id else None)
                )
                if row:
                    lat, lng = row.latitude, row.longitude

        result = scoped_products(
            lat, lng, limit=args["limit"], cursor=args.get("cursor")
        )
        distances = result["distances_km"]

        return {
            "items": [
                {
                    "id": p.id,
                    "name": p.name,
                    "price": float(p.price) if p.price is not None else None,
                    "seller_id": p.seller_id,
                    "distance_km": distances.get(p.id),
                }
                for p in result["items"]
            ],
            "scope": result["scope"],
            "radius_km": result["radius_km"],
            "next_cursor": result["next_cursor"],
        }
