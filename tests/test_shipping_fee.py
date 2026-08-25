"""Unit tests for CartService._calculate_shipping_fee (1.1/10.3): flat fee
per distinct market among the cart's sellers, replacing the old hardcoded
flat ₦10 regardless of cart contents."""

from types import SimpleNamespace

from app.cart.services import CartService
from app.deliveries.runs import DEFAULT_BASE_PRICE

_ADDRESS = {"city": "Ibadan"}


def _item(market_id):
    seller = SimpleNamespace(market_id=market_id) if market_id is not None else None
    return SimpleNamespace(product=SimpleNamespace(seller=seller))


def test_calculate_shipping_fee_zero_without_address():
    cart = SimpleNamespace(items=[_item(1)])
    assert CartService._calculate_shipping_fee(cart, None) == 0.0


def test_calculate_shipping_fee_zero_for_empty_cart():
    cart = SimpleNamespace(items=[])
    assert CartService._calculate_shipping_fee(cart, _ADDRESS) == 0.0


def test_calculate_shipping_fee_single_market_charges_once():
    cart = SimpleNamespace(items=[_item(1), _item(1)])
    assert CartService._calculate_shipping_fee(cart, _ADDRESS) == DEFAULT_BASE_PRICE


def test_calculate_shipping_fee_multi_market_charges_per_distinct_market():
    cart = SimpleNamespace(items=[_item(1), _item(2)])
    assert CartService._calculate_shipping_fee(cart, _ADDRESS) == DEFAULT_BASE_PRICE * 2


def test_calculate_shipping_fee_unresolved_seller_counts_as_one_delivery():
    # No seller/market_id at all (e.g. a test fixture or a seller that
    # somehow has no market assigned) -- still charged, not dropped.
    cart = SimpleNamespace(items=[_item(None)])
    assert CartService._calculate_shipping_fee(cart, _ADDRESS) == DEFAULT_BASE_PRICE


def test_calculate_shipping_fee_resolved_and_unresolved_both_counted():
    cart = SimpleNamespace(items=[_item(1), _item(None)])
    assert CartService._calculate_shipping_fee(cart, _ADDRESS) == DEFAULT_BASE_PRICE * 2
