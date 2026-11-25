"""Marking business orders.

An order is a business order when its buyer counts as a business account at
the moment the order is created. Stamped on the row (Order.is_business) rather
than worked out on read, so a subscription lapsing later doesn't rewrite
order history — the same rule as BuyerRequest.is_business.

Called explicitly from each place an Order is built (OrderService.create_order,
create_order_from_checkout_snapshot and CartService.checkout_cart), inside the
caller's transaction.
"""

from .entitlements import EntitlementService


def stamp_business_order(session, order, buyer_id) -> None:
    from app.users.models import Buyer

    buyer = session.query(Buyer).get(buyer_id) if buyer_id is not None else None
    order.is_business = bool(buyer and EntitlementService.is_business(buyer.user))
