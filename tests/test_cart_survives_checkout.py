"""The basket is emptied by paying, not by checking out.

Clearing at checkout meant a buyer who backed out of the payment screen --
to change a quantity, to add one more thing, or because they simply were not
ready -- came back to an empty cart and an order they had not agreed to pay
for. These pin the new rule and the two things it must not break.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.payments.services import PaymentService


def _order_item(product_id, variant_id=None):
    return SimpleNamespace(product_id=product_id, variant_id=variant_id)


def _cart_item(product_id, variant_id=None):
    return SimpleNamespace(product_id=product_id, variant_id=variant_id)


def _order(items, buyer_id=1, user_id="USR_1", order_id="ORD_1"):
    return SimpleNamespace(
        id=order_id,
        buyer_id=buyer_id,
        buyer=SimpleNamespace(user_id=user_id),
        items=items,
    )


def _run(order, cart_items):
    """Call the tidier against a stub cart, and report what was deleted."""
    cart = SimpleNamespace(buyer_id=order.buyer_id, items=cart_items)
    session = MagicMock()
    deleted = []
    session.delete.side_effect = deleted.append

    with patch("app.cart.services.CartService.resolve_cart", return_value=cart), patch(
        "app.cart.services.CartService._invalidate_cart_cache"
    ):
        PaymentService._clear_purchased_items_from_cart(session, order)
    return deleted


def test_paying_takes_the_bought_items_out_of_the_cart():
    bought = _cart_item("PRD_A")
    deleted = _run(_order([_order_item("PRD_A")]), [bought])
    assert deleted == [bought]


def test_something_added_while_the_order_sat_unpaid_survives():
    """The whole point of keeping the cart: a buyer goes back, adds another
    product, then pays the original order. The new item is still wanted."""
    bought = _cart_item("PRD_A")
    added_later = _cart_item("PRD_B")
    deleted = _run(_order([_order_item("PRD_A")]), [bought, added_later])
    assert deleted == [bought]
    assert added_later not in deleted


def test_variants_are_told_apart():
    # Same product, different size. Paying for one must not remove the other.
    small = _cart_item("PRD_A", variant_id=1)
    large = _cart_item("PRD_A", variant_id=2)
    deleted = _run(_order([_order_item("PRD_A", variant_id=1)]), [small, large])
    assert deleted == [small]


def test_an_empty_order_clears_nothing():
    keep = _cart_item("PRD_A")
    assert _run(_order([]), [keep]) == []


def test_a_cart_that_cannot_be_read_never_fails_the_payment():
    """The money has already moved. A cart that could not be tidied is
    cosmetic; raising here would fail a payment that went through."""
    session = MagicMock()
    with patch(
        "app.cart.services.CartService.resolve_cart",
        side_effect=RuntimeError("redis is down"),
    ):
        # No raise.
        PaymentService._clear_purchased_items_from_cart(
            session, _order([_order_item("PRD_A")])
        )


def test_an_order_with_no_buyer_is_skipped_quietly():
    order = SimpleNamespace(
        id="ORD_1", buyer_id=1, buyer=None, items=[_order_item("PRD_A")]
    )
    session = MagicMock()
    PaymentService._clear_purchased_items_from_cart(session, order)
    session.delete.assert_not_called()
