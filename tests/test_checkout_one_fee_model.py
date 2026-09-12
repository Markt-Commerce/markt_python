"""Both checkout flows price a basket the same way.

The order-first flow charged 5% VAT and no Service Fee; the payment-first
flow charged a Service Fee and no VAT, because Phase 0 deferred VAT. So the
same basket cost a different amount depending on which endpoint the app
happened to call, and the live one was collecting a tax line Markt does not
remit while collecting none of the fee it does.

These pin the single model: no VAT, a Service Fee on what the buyer actually
pays for goods.
"""

from decimal import Decimal

import pytest

from app.orders.fees import (
    SERVICE_FEE_CEILING,
    SERVICE_FEE_FLOOR,
    build_fee_breakdown,
    calculate_service_fee,
)


def order_first_total(subtotal, shipping_fee, discount=Decimal("0.00")):
    """The arithmetic CartService.checkout_cart now does, in one place so a
    change to it has to change this file too."""
    tax = Decimal("0.00")
    service_fee = calculate_service_fee(subtotal - discount)
    return subtotal + shipping_fee + tax + service_fee - discount


def test_the_two_flows_agree_on_an_undiscounted_basket():
    subtotal, shipping = Decimal("5000.00"), Decimal("500.00")
    payment_first = build_fee_breakdown(subtotal, shipping)["total"]
    assert order_first_total(subtotal, shipping) == payment_first


@pytest.mark.parametrize("subtotal", ["500.00", "5000.00", "50000.00", "500000.00"])
def test_they_agree_at_every_size(subtotal):
    subtotal = Decimal(subtotal)
    shipping = Decimal("500.00")
    assert (
        order_first_total(subtotal, shipping)
        == build_fee_breakdown(subtotal, shipping)["total"]
    )


def test_no_vat_is_charged():
    """5% of 5,000 is 250. If that ever comes back, this fails."""
    subtotal, shipping = Decimal("5000.00"), Decimal("500.00")
    expected_without_tax = subtotal + shipping + calculate_service_fee(subtotal)
    assert order_first_total(subtotal, shipping) == expected_without_tax


def test_the_service_fee_is_charged_on_what_the_buyer_pays_for_goods():
    """A seller's N1,000 discount is the seller's to give. Taking 2.5% of it
    back as a fee would quietly undo part of the gesture."""
    subtotal, discount = Decimal("40000.00"), Decimal("1000.00")
    total = order_first_total(subtotal, Decimal("0.00"), discount)
    assert total == subtotal - discount + calculate_service_fee(subtotal - discount)
    assert calculate_service_fee(subtotal - discount) == Decimal("975.00")


def test_a_tiny_order_still_pays_the_floor():
    assert calculate_service_fee(Decimal("100.00")) == SERVICE_FEE_FLOOR


def test_a_discount_cannot_drag_the_fee_below_the_floor():
    """Even a discount that takes the basket to nothing leaves the floor --
    servicing the order still costs the same."""
    assert calculate_service_fee(Decimal("10000.00") - Decimal("9900.00")) == (
        SERVICE_FEE_FLOOR
    )


def test_a_large_basket_is_capped():
    assert calculate_service_fee(Decimal("10000000.00")) == SERVICE_FEE_CEILING


def test_a_basket_discounted_to_nothing_owes_only_delivery():
    """No floor here: calculate_service_fee treats a zero basket as no
    basket, and a buyer whose goods were given away should not be charged a
    fee for servicing nothing. They still pay to have it brought to them."""
    subtotal = Decimal("2000.00")
    total = order_first_total(subtotal, Decimal("700.00"), subtotal)
    assert total == Decimal("700.00")


def test_the_fee_is_decimal_all_the_way_through():
    """Money math stays in Decimal; a float sneaking in is how rounding
    errors get into totals."""
    assert isinstance(order_first_total(Decimal("5000.00"), Decimal("500.00")), Decimal)
