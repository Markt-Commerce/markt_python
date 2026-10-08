"""One basket, several shops, several orders.

A delivery quote prices one pickup to one dropoff, so a basket spanning two
shops is two deliveries. Until this existed a buyer could build such a basket
and have no way out but deleting items one at a time.
"""

from types import SimpleNamespace

from app.cart.grouping import group_cart_items


def _item(seller_id, price=1000, qty=1, shop="A Shop", item_id=None):
    seller = (
        SimpleNamespace(shop_name=shop, shop_slug=shop.lower(), banner_url=None)
        if seller_id is not None
        else None
    )
    product = SimpleNamespace(seller_id=seller_id, seller=seller)
    return SimpleNamespace(
        id=item_id or seller_id, product=product, product_price=price, quantity=qty
    )


def test_one_shop_is_one_group():
    groups = group_cart_items([_item(1), _item(1)])
    assert len(groups) == 1
    assert groups[0].item_count == 2


def test_two_shops_are_two_groups():
    groups = group_cart_items([_item(1, shop="Alice"), _item(2, shop="Bola")])
    assert [g.seller_id for g in groups] == [1, 2]
    assert [g.shop_name for g in groups] == ["Alice", "Bola"]


def test_each_group_totals_only_its_own_items():
    """A cart-wide total would be a number the buyer can never actually pay,
    because each group checks out separately."""
    groups = group_cart_items([_item(1, price=1000, qty=2), _item(2, price=500, qty=3)])
    by_seller = {g.seller_id: g for g in groups}
    assert by_seller[1].subtotal == 2000
    assert by_seller[2].subtotal == 1500


def test_the_order_of_groups_is_stable():
    """A cart whose sections reshuffle between two loads of the same screen
    looks broken even when nothing changed."""
    items = [_item(3), _item(1), _item(2)]
    first = [g.seller_id for g in group_cart_items(items)]
    second = [g.seller_id for g in group_cart_items(list(reversed(items)))]
    assert first == second == [1, 2, 3]


def test_an_item_with_no_resolvable_shop_is_still_shown():
    """A buyer who can see something in their basket must be able to act on
    it. Dropping it turns an awkward cart into an invisible one."""
    groups = group_cart_items([_item(1), _item(None, item_id="orphan")])
    assert len(groups) == 2
    assert any(g.seller_id is None for g in groups)


def test_orphans_sort_last():
    groups = group_cart_items([_item(None, item_id="x"), _item(2)])
    assert [g.seller_id for g in groups] == [2, None]


def test_an_empty_cart_has_no_groups():
    assert group_cart_items([]) == []
    assert group_cart_items(None) == []
