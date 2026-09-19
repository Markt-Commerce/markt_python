"""Splitting one basket into the orders it will actually become.

A Markt cart can hold items from several shops, but a delivery cannot: a
quote prices one pickup to one dropoff, and checkout refuses a basket that
spans more than one seller. Until now nothing stopped a buyer building such a
basket, so it was possible to fill a cart that could never be paid for and
have no way out but deleting things one at a time.

So the cart is presented as what it really is -- one group per shop, each of
which checks out on its own. Nothing is moved or deleted; this is a view over
the same cart rows.

Grouped by seller rather than by market, deliberately. The market is how
Markt files a shop; the seller is who hands the parcel to the rider. Two
shops in one market are still two pickups and therefore two deliveries, and
grouping by market would rebuild exactly the basket checkout refuses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.libs.money import to_money


@dataclass
class CartGroup:
    """Everything in the basket from one shop."""

    seller_id: int
    shop_name: Optional[str]
    shop_slug: Optional[str]
    banner_url: Optional[str]
    items: List[Any] = field(default_factory=list)

    @property
    def item_count(self) -> int:
        return sum(getattr(i, "quantity", 0) or 0 for i in self.items)

    @property
    def subtotal(self) -> Decimal:
        total = Decimal("0")
        for item in self.items:
            price = to_money(getattr(item, "product_price", 0)) or Decimal("0")
            total += price * (getattr(item, "quantity", 0) or 0)
        return to_money(total)


def group_cart_items(items) -> List[CartGroup]:
    """One group per shop, in a stable order.

    Sorted by seller id rather than by whatever the database returned, so the
    groups do not reshuffle between two loads of the same screen -- a cart
    whose sections move around looks broken even when nothing changed.

    An item whose product or seller cannot be resolved still gets a group of
    its own rather than being silently dropped. A buyer who can see something
    in their basket must be able to act on it; hiding it is how an
    un-checkout-able cart becomes invisible instead of merely awkward.
    """
    groups: Dict[Any, CartGroup] = {}

    for item in items or []:
        product = getattr(item, "product", None)
        seller = getattr(product, "seller", None) if product else None
        seller_id = getattr(product, "seller_id", None) if product else None

        key = (
            seller_id
            if seller_id is not None
            else f"unknown:{getattr(item, 'id', id(item))}"
        )
        if key not in groups:
            groups[key] = CartGroup(
                seller_id=seller_id,
                shop_name=getattr(seller, "shop_name", None),
                shop_slug=getattr(seller, "shop_slug", None),
                banner_url=getattr(seller, "banner_url", None),
            )
        groups[key].items.append(item)

    return sorted(
        groups.values(),
        key=lambda g: (g.seller_id is None, g.seller_id or 0),
    )
