"""Moving a delivery forward once the money is good.

A delivery is created at QUOTED when the order is. Two things then have to
happen, and neither of them had anywhere to live before this module:

  * the delivery has to learn that the order was paid for, and
  * somebody has to be asked to actually carry the parcel.

They are deliberately separate. Marking paid happens inside the payment's own
transaction, because a delivery that thinks it is unpaid for an order that is
paid is a bookkeeping lie. Creating the courier job happens *after* that
transaction commits, because it calls out to another company over the network
and must never be able to roll back a payment that already succeeded -- or,
worse, create a real courier job for an order that then failed to commit.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.libs.session import session_scope

from .logistics import JobRequest, get_adapter
from .order_delivery import DeliveryState, OrderDelivery

logger = logging.getLogger(__name__)


def mark_paid(session, order_id: str) -> Optional[OrderDelivery]:
    """QUOTED -> PAID, inside the caller's transaction.

    Idempotent and quiet. A payment can be completed twice -- Paystack's
    webhook and the browser callback both land, by design -- so arriving at a
    delivery that is already PAID, or already out with a rider, is normal
    traffic rather than an error.

    Never raises into a payment completion. The money is already taken; a
    delivery that could not be advanced is something an operator can fix,
    while an exception here would fail a completion that has no business
    failing.
    """
    try:
        delivery = session.query(OrderDelivery).filter_by(order_id=order_id).first()
        if delivery is None:
            # Normal: an order checked out without a quote has no delivery row.
            return None
        if delivery.state is not DeliveryState.QUOTED:
            return delivery
        delivery.transition_to(DeliveryState.PAID)
        logger.info("Delivery for order %s is paid", order_id)
        return delivery
    except Exception:
        logger.exception(
            "Could not mark the delivery for order %s paid -- the payment "
            "stands and the delivery needs advancing by hand",
            order_id,
        )
        return None


def dispatch(order_id: str) -> bool:
    """PAID -> JOB_CREATED, in its own transaction, after the payment committed.

    Returns True when a courier job now exists.

    A provider that will not take the job does not fail the order. The buyer
    has paid and is owed a delivery, so it parks at AWAITING_DISPATCH where an
    operator can see it, rather than pretending dispatch succeeded or throwing
    the order away.
    """
    with session_scope() as session:
        delivery = session.query(OrderDelivery).filter_by(order_id=order_id).first()
        if delivery is None:
            return False
        if delivery.state is not DeliveryState.PAID:
            # Either not paid yet, or a job already exists. Both mean there is
            # nothing to do here, and a second webhook must not create a
            # second courier job.
            return False

        order = delivery.order
        request = _job_request_for(delivery, order)

        adapter = get_adapter()
        try:
            job = adapter.create_job(request)
        except Exception as exc:
            # Deliberately broad, and LogisticsError is only the polite case.
            # An adapter talking to someone else's API can raise anything at
            # all -- a timeout, a JSON error, a DNS failure -- and none of
            # those are a reason to lose a paid order.
            logger.error(
                "Logistics provider %r refused the job for order %s: %s",
                getattr(adapter, "name", "?"),
                order_id,
                exc,
            )
            delivery.transition_to(DeliveryState.AWAITING_DISPATCH)
            return False

        delivery.external_job_id = job.reference
        delivery.transition_to(DeliveryState.JOB_CREATED)
        logger.info(
            "Order %s dispatched to %s as job %s",
            order_id,
            job.provider,
            job.reference,
        )
        return True


def _job_request_for(delivery: OrderDelivery, order) -> JobRequest:
    """Everything the provider needs, and nothing it does not.

    Coordinates come from the delivery's own snapshot rather than being
    re-resolved: that is where the parcel was priced to go, and re-deriving it
    now could quietly send a rider somewhere the buyer was never charged for.
    """
    address = getattr(order, "shipping_address", None)
    buyer_user = getattr(getattr(order, "buyer", None), "user", None)

    seller = None
    items = getattr(order, "items", None) or []
    for item in items:
        seller = getattr(item, "seller", None)
        if seller is not None:
            break

    return JobRequest(
        order_id=order.id,
        pickup_lat=delivery.pickup_lat,
        pickup_lng=delivery.pickup_lng,
        pickup_contact=getattr(seller, "shop_name", None) or "Markt seller",
        dropoff_lat=delivery.dropoff_lat,
        dropoff_lng=delivery.dropoff_lng,
        dropoff_contact=(getattr(address, "recipient_name", None) or "Markt customer"),
        # The address model has no phone column; the courier's callback number
        # is the buyer's own.
        dropoff_phone=getattr(buyer_user, "phone_number", None),
        item_count=sum(getattr(i, "quantity", 0) or 0 for i in items),
        # Not carried on the delivery snapshot, and re-summing it from the
        # products now could disagree with what the quote was priced on.
        # Sent as 0 until there is a reason for the provider to have it.
        total_weight_grams=0,
        fee_minor=delivery.effective_fee_minor,
        notes=getattr(order, "customer_note", None),
    )


def cancel_for_order(session, order_id: str) -> Optional[OrderDelivery]:
    """Cancel the delivery attached to an order, if that is still honest.

    Raises ValidationError when the parcel is already in someone's hands.
    Past pickup, cancelling stops being a state change and becomes a return:
    a rider has to carry it back, which costs real money and is a different
    process with different rules. Letting the buyer cancel there would refund
    a delivery fee for work that was actually done.

    Called inside the caller's transaction and *before* the order is mutated,
    so a refusal leaves the order exactly as it was.
    """
    from app.libs.errors import ValidationError

    delivery = session.query(OrderDelivery).filter_by(order_id=order_id).first()
    if delivery is None:
        return None  # no quote was used; nothing to cancel

    if delivery.state is DeliveryState.CANCELLED:
        return delivery  # already done; cancelling twice is not an error

    if DeliveryState.CANCELLED not in OrderDelivery.VALID_TRANSITIONS.get(
        delivery.state, []
    ):
        raise ValidationError(
            "This order is already out for delivery and can't be cancelled. "
            "Please refuse it at the door or start a return instead."
        )

    was = delivery.state.value
    delivery.transition_to(DeliveryState.CANCELLED)
    logger.info("Delivery for order %s cancelled from %s", order_id, was)
    return delivery
