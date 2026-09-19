"""Holding an order for a rider while they decide, without losing it.

A rider tapping an available order used to accept it in the same gesture.
The app now shows a countdown, which only means anything if the order is
genuinely held for that rider while it runs -- otherwise the timer is
decoration and two riders can still take the same order half a second apart.

The whole design is shaped around one failure mode: **an order nobody is
carrying, that nobody can see.** Every rule here exists to make that
impossible.

* **The hold lives on the server, with an expiry.** Never on the phone. A
  rider who backgrounds the app, rides into a basement or runs out of
  battery must not be able to hold an order hostage, and the one thing you
  cannot rely on to release a lock is the client that took it. Nothing has
  to call back for a hold to end; it ends by the clock.

* **A decline is temporary.** It used to be permanent -- one tap and that
  rider could never see the order again, with nothing anywhere to put it
  back. In an area with three riders, three taps made an order invisible to
  every rider near it, forever. A decline now hides it from that rider for
  ``DECLINE_COOLDOWN``, then it comes back if it is still going.

* **Letting an offer lapse is not a decline.** A rider who missed the
  countdown said nothing about whether they wanted the order, so it returns
  to them almost immediately rather than serving a cooldown.

* **Escalation beats waiting.** An order still unclaimed after
  ``ESCALATE_AFTER`` is re-alerted on a widened radius, including to riders
  who declined it. Sitting quietly in a list that nobody is refreshing is
  how an order gets forgotten.

The sweep in tasks.py is what actually enforces the first and last of
those; this module holds the rules and the arithmetic so both the request
path and the sweep agree on them.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.deliveries.models import AssignmentStatus, DeliveryOrderAssignment

logger = logging.getLogger(__name__)

# How long a rider has to make up their mind. Long enough to read a pickup
# and a drop-off and think about the traffic between them; short enough that
# an order is not parked while somebody else could be riding to it.
OFFER_SECONDS = 30

# How long an order stays out of a rider's list after they decline it. They
# said no to this order now -- at the end of a shift, mid-delivery, heading
# the other way -- not to this order forever.
DECLINE_COOLDOWN = timedelta(minutes=10)

# A lapsed offer is not a decision, so it comes back quickly. Not instantly:
# re-offering the same order to the same idle phone in a loop is how you
# turn one uninterested rider into a wall between an order and everyone
# else.
LAPSE_COOLDOWN = timedelta(minutes=2)

# How many single orders a rider may be carrying at once.
#
# There was no limit at all: a rider could accept every order on the
# dashboard and then deliver them at whatever pace they liked, while every
# one of those buyers watched an order that was technically "on its way".
#
# One is what Uber Eats, Bolt Food and Glovo all do for an individual
# courier, and the reason is the same everywhere: a rider holding five
# orders is not five times faster, they are one rider with four orders
# going cold. Batching is supposed to come from the platform, which can see
# every order and route them together -- that is what delivery runs are. A
# rider hoarding orders is batching by accident, in whatever order occurs
# to them.
#
# Two rather than one, because a rider who has handed over their last
# package but not yet scanned the code should be able to take the next job
# rather than stand still.
MAX_CONCURRENT_ORDERS = 2

# After this long unclaimed, stop waiting for the neighbourhood and widen
# the net.
ESCALATE_AFTER = timedelta(minutes=10)

# Each escalation reaches further out. Capped, because past a point the ride
# to the pickup costs more than the delivery pays and a rider who accepts is
# worse off for it.
ESCALATION_RADII_KM = (5.0, 10.0, 20.0)


def now() -> datetime:
    """One clock, so the request path and the sweep agree on 'expired'."""
    return datetime.utcnow()


def offer_expiry(at: Optional[datetime] = None) -> datetime:
    return (at or now()) + timedelta(seconds=OFFER_SECONDS)


def is_live_offer(
    assignment: DeliveryOrderAssignment, at: Optional[datetime] = None
) -> bool:
    """A hold that is still running.

    An OFFERED row whose expiry has passed is not a hold. It is a row the
    sweep has not reached yet, and it must never keep an order off anyone
    else's list -- the sweep runs on a schedule, and an order's availability
    cannot wait on a scheduler.
    """
    if assignment.status != AssignmentStatus.OFFERED:
        return False
    if assignment.expires_at is None:
        # A hold with no expiry is the exact thing this module exists to
        # prevent. Treat it as already over rather than as forever.
        logger.warning(
            "Assignment %s is OFFERED with no expiry; treating as lapsed",
            assignment.assignment_id,
        )
        return False
    return assignment.expires_at > (at or now())


def suppresses_for_rider(
    assignment: DeliveryOrderAssignment, at: Optional[datetime] = None
) -> bool:
    """Whether this row should keep the order out of *this* rider's list.

    Only three things do: a live hold, a decline still inside its cooldown,
    and a lapse still inside its (much shorter) one. Everything else -- an
    old decline, a lapsed offer, a failed assignment -- leaves the order
    visible, because a rider who cannot see an order cannot take it.
    """
    at = at or now()
    if assignment.status == AssignmentStatus.OFFERED:
        return is_live_offer(assignment, at)
    if assignment.status in (AssignmentStatus.REJECTED, AssignmentStatus.EXPIRED):
        return assignment.expires_at is not None and assignment.expires_at > at
    return False


def decline_until(at: Optional[datetime] = None) -> datetime:
    return (at or now()) + DECLINE_COOLDOWN


def lapse_until(at: Optional[datetime] = None) -> datetime:
    return (at or now()) + LAPSE_COOLDOWN


def escalation_radius_km(unclaimed_for: timedelta) -> Optional[float]:
    """How far to look for a rider, given how long nobody has taken this.

    Returns None while the order is still young enough that the ordinary
    nearby alert has not had its chance yet.
    """
    if unclaimed_for < ESCALATE_AFTER:
        return None
    steps = int(unclaimed_for / ESCALATE_AFTER)
    index = min(steps - 1, len(ESCALATION_RADII_KM) - 1)
    return ESCALATION_RADII_KM[max(index, 0)]


def sweep() -> dict:
    """Release lapsed holds and chase unclaimed orders.

    Called from the beat schedule. Everything here is idempotent and safe to
    run twice: it works off timestamps, not off having-been-run.
    """
    from app.deliveries.rider_alerts import alert_nearby_riders
    from app.libs.session import session_scope
    from app.orders.models import Order, OrderStatus

    at = now()
    lapsed = 0
    realerted = 0
    escalated = 0

    # 1. Holds whose time is up. Marked EXPIRED with a short cooldown, so
    #    the order is immediately available to everyone else and comes back
    #    to this rider shortly -- letting a countdown run out is not a
    #    decision about the order.
    with session_scope() as session:
        stale = (
            session.query(DeliveryOrderAssignment)
            .filter(
                DeliveryOrderAssignment.status == AssignmentStatus.OFFERED,
                DeliveryOrderAssignment.expires_at <= at,
            )
            .all()
        )
        lapsed_order_ids = []
        for row in stale:
            row.status = AssignmentStatus.EXPIRED
            row.expires_at = lapse_until(at)
            lapsed_order_ids.append(row.order_id)
            lapsed += 1

    # 2. Anything whose hold just lapsed goes back on the air, so the next
    #    rider hears about it rather than waiting to notice it in a list.
    for order_id in set(lapsed_order_ids):
        if alert_nearby_riders(order_id):
            realerted += 1

    # 3. Orders nobody has taken. Re-alerted on a widening radius, including
    #    to riders who declined -- their cooldown is about this minute, not
    #    about the order.
    with session_scope() as session:
        waiting = (
            session.query(Order)
            .filter(Order.status == OrderStatus.READY_FOR_DELIVERY)
            .all()
        )
        order_ids = [order.id for order in waiting]
        taken = set()
        held = set()
        if order_ids:
            rows = (
                session.query(DeliveryOrderAssignment)
                .filter(DeliveryOrderAssignment.order_id.in_(order_ids))
                .all()
            )
            for row in rows:
                if row.status == AssignmentStatus.ACCEPTED:
                    taken.add(row.order_id)
                elif is_live_offer(row, at):
                    held.add(row.order_id)

        chase = []
        for order in waiting:
            if order.id in taken or order.id in held:
                continue
            since = order.updated_at or order.created_at
            if since is None:
                continue
            radius = escalation_radius_km(at - since)
            if radius is not None:
                chase.append((order.id, radius))

    for order_id, radius in chase:
        if alert_nearby_riders(order_id, radius_km=radius):
            escalated += 1

    return {"lapsed": lapsed, "realerted": realerted, "escalated": escalated}
