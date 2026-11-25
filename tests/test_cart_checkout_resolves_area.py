"""Cart checkout stamps the delivery Area on the order's shipping address.

Delivery runs group orders by (market, area) and only consider orders whose
shipping address has an area. The payment-first checkout resolved it; cart
checkout -- the path the app uses -- did not, so no app order could ever join
a shared run, even when the buyer had opted in and paid the solo fee.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.cart.services import CartService


def test_area_is_stamped_when_one_is_near_enough():
    address = SimpleNamespace(latitude=7.4466, longitude=3.8959, area_id=None)
    with patch(
        "app.markets.services.MarketService.resolve_area_for_coordinates",
        return_value=SimpleNamespace(id=4),
    ) as resolve:
        CartService._resolve_shipping_area(MagicMock(), address)
    assert address.area_id == 4
    assert resolve.call_args.args[1:] == (7.4466, 3.8959)


def test_left_unset_when_nothing_is_near():
    address = SimpleNamespace(latitude=9.07, longitude=7.39, area_id=None)
    with patch(
        "app.markets.services.MarketService.resolve_area_for_coordinates",
        return_value=None,
    ):
        CartService._resolve_shipping_area(MagicMock(), address)
    assert address.area_id is None


def test_checkout_calls_it():
    """Guard against the call being dropped from checkout_cart again."""
    import inspect

    assert "_resolve_shipping_area" in inspect.getsource(CartService.checkout_cart)
