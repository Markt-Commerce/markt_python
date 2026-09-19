"""Telling riders a delivery exists.

The rider app's dashboard lists what is available nearby, and until now that
was the only way to find out: a rider had to be looking at the screen at the
moment an order was paid for. This pushes instead, to the riders close enough
to take it.

Deliberately cheap and deliberately quiet. It runs after a payment has
committed, on a path that must never fail a paid order, so everything here is
best-effort and swallowed.
"""

import logging
from typing import List, Optional

from app.libs.geo import haversine_km
from app.libs.session import read_scope

logger = logging.getLogger(__name__)

# Roughly the radius the available-orders list itself uses (5 km), so a rider
# is not pushed about something that will not appear when they open the app.
ALERT_RADIUS_KM = 5.0

# A cap, so one order in a dense market does not wake every rider in the city.
MAX_RIDERS_ALERTED = 25


def _nearby_rider_ids(
    session, lat: float, lng: float, radius_km: float = ALERT_RADIUS_KM
) -> List[str]:
    from app.deliveries.models import (
        DeliveryLastLocation,
        DeliveryStatus,
        DeliveryUser,
    )

    rows = (
        session.query(DeliveryUser.id, DeliveryLastLocation)
        .join(
            DeliveryLastLocation,
            DeliveryLastLocation.delivery_user_id == DeliveryUser.id,
        )
        .filter(DeliveryUser.status == DeliveryStatus.ACTIVE)
        .all()
    )

    near = []
    for rider_id, location in rows:
        if location is None or location.latitude is None or location.longitude is None:
            continue
        distance = haversine_km(lat, lng, location.latitude, location.longitude)
        if distance <= radius_km:
            near.append((distance, rider_id))

    near.sort()
    return [rider_id for _, rider_id in near[:MAX_RIDERS_ALERTED]]


def alert_nearby_riders(
    order_id: str,
    pickup_name: Optional[str] = None,
    radius_km: float = ALERT_RADIUS_KM,
) -> int:
    """Push "a delivery is available" to riders near the pickup.

    `radius_km` widens for escalation: an order nobody has taken after a
    while is re-alerted further out (see app/deliveries/offers.py), because
    an order sitting unclaimed in a list nobody is refreshing is how one
    gets forgotten.

    Returns how many were told. Never raises.
    """
    try:
        from app.notifications.models import NotificationType
        from app.notifications.services import NotificationService
        from app.orders.models import Order

        with read_scope() as session:
            order = session.query(Order).get(order_id)
            if order is None:
                return 0

            # The pickup, resolved the same way available-orders resolves it:
            # the shop's own coordinates.
            seller = next(
                (item.seller for item in order.items if item.seller is not None),
                None,
            )
            if seller is None:
                return 0
            lat, lng = seller.shop_latitude, seller.shop_longitude
            if lat is None or lng is None:
                return 0

            shop_name = pickup_name or getattr(seller, "shop_name", None) or "a shop"
            rider_ids = _nearby_rider_ids(session, lat, lng, radius_km)

        for rider_id in rider_ids:
            NotificationService.create_notification(
                rider_id,
                NotificationType.DELIVERY_AVAILABLE,
                reference_type="order",
                reference_id=str(order_id),
                metadata_={
                    "pickup": f"Pick up from {shop_name}.",
                    "order_id": order_id,
                },
            )
        return len(rider_ids)
    except Exception:
        logger.exception("Could not alert riders about order %s", order_id)
        return 0
