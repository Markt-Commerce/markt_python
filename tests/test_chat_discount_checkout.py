"""A discount offered in chat, spent at checkout -- once, and only here.

The offer used to be burned by *asking* what it was worth: the preview call
incremented usage_count and committed. So a buyer who opened their basket
twice had spent a single-use offer without buying anything, and a seller's
goodwill evaporated on a page view.

The rule these pin down is: checking is free, buying spends. And an offer is
one seller's, so it may only come off that seller's bill.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.cart.services import CartService
from app.chats.models import ChatDiscount, DiscountStatus, DiscountType
from app.chats.services import DiscountService
from app.libs.errors import ValidationError

BUYER = "USR_BUYER"
SELLER = "USR_SELLER"
OTHER_SELLER = "USR_OTHER"


def _discount(**overrides):
    """A real ChatDiscount, unattached to any session.

    Real rather than a stub on purpose: can_be_applied_to_order and
    calculate_discount_amount are the rules under test, and a stub would
    only prove the test agrees with itself.
    """
    discount = ChatDiscount()
    discount.id = 1
    discount.discount_type = DiscountType.FIXED_AMOUNT
    discount.discount_value = 500.0
    discount.minimum_order_amount = None
    discount.maximum_discount_amount = None
    discount.expires_at = datetime.utcnow() + timedelta(days=1)
    discount.usage_limit = 1
    discount.usage_count = 0
    discount.status = DiscountStatus.ACCEPTED
    discount.created_by_id = SELLER
    discount.offered_to_id = BUYER
    for key, value in overrides.items():
        setattr(discount, key, value)
    return discount


def _session(found):
    """A session that returns `found` for the locking lookup."""
    session = MagicMock()
    chain = session.query.return_value.filter.return_value.with_for_update.return_value
    chain.first.return_value = found
    return session


def _validate(discount, *, amount=5000.0, seller=SELLER, buyer=BUYER):
    return DiscountService.validate_for_order(
        _session(discount),
        buyer_user_id=buyer,
        discount_id=1,
        order_amount=amount,
        seller_user_id=seller,
    )


# --- what an offer is worth -------------------------------------------------


def test_a_live_offer_comes_off_the_bill():
    found, amount, _ = _validate(_discount())
    assert found is not None
    assert amount == 500.0


def test_a_percentage_offer_is_taken_off_the_basket_total():
    found, amount, _ = _validate(
        _discount(discount_type=DiscountType.PERCENTAGE, discount_value=10.0),
        amount=5000.0,
    )
    assert found is not None
    assert amount == 500.0


def test_an_offer_bigger_than_the_basket_cannot_go_negative():
    """A N5,000-off offer against a N1,200 basket is N1,200 off, not N5,000.

    Otherwise the total is negative and Markt pays the buyer to shop.
    """
    _, amount, _ = _validate(_discount(discount_value=5000.0), amount=1200.0)
    assert amount == 1200.0


def test_a_minimum_order_is_enforced():
    found, amount, message = _validate(
        _discount(minimum_order_amount=10000.0), amount=5000.0
    )
    assert found is None
    assert amount == 0.0
    assert "₦" in message and "$" not in message  # naira app, naira copy


# --- whose offer it is ------------------------------------------------------


def test_another_shops_offer_does_not_discount_this_shop():
    found, amount, message = _validate(_discount(), seller=OTHER_SELLER)
    assert found is None
    assert amount == 0.0
    assert "different shop" in message


def test_an_offer_made_to_someone_else_is_simply_not_found():
    """Scoped in the query itself, so another buyer's id finds nothing --
    and the message does not confirm the id exists."""
    session = _session(None)
    found, amount, message = DiscountService.validate_for_order(
        session,
        buyer_user_id="USR_STRANGER",
        discount_id=1,
        order_amount=5000.0,
        seller_user_id=SELLER,
    )
    assert (found, amount) == (None, 0.0)
    assert "not found" in message.lower()


# --- spent once, and only by buying ----------------------------------------


def test_an_already_spent_offer_says_so():
    """Not "Discount is not valid" -- a buyer cannot act on that."""
    found, _, message = _validate(_discount(usage_count=1))
    assert found is None
    assert "already been used" in message.lower()


def test_an_expired_offer_says_so_before_anyone_marks_it_expired():
    """Nothing sweeps these to EXPIRED, so the status is still ACCEPTED when
    the buyer tries to use it."""
    found, _, message = _validate(
        _discount(expires_at=datetime.utcnow() - timedelta(days=2))
    )
    assert found is None
    assert "expired" in message.lower()


def test_an_expired_offer_is_refused():
    found, _, _ = _validate(
        _discount(expires_at=datetime.utcnow() - timedelta(minutes=1))
    )
    assert found is None


def test_a_rejected_offer_is_refused():
    found, _, _ = _validate(_discount(status=DiscountStatus.REJECTED))
    assert found is None


def test_checking_what_an_offer_is_worth_does_not_spend_it():
    """The regression that started this. Validation is a read."""
    discount = _discount()
    session = _session(discount)
    DiscountService.validate_for_order(
        session,
        buyer_user_id=BUYER,
        discount_id=1,
        order_amount=5000.0,
        seller_user_id=SELLER,
    )
    assert discount.usage_count == 0
    assert discount.status == DiscountStatus.ACCEPTED
    session.commit.assert_not_called()


def test_buying_spends_it():
    discount = _discount()
    DiscountService.consume(MagicMock(), discount)
    assert discount.usage_count == 1
    assert discount.status == DiscountStatus.USED
    assert discount.used_at is not None


def test_a_multi_use_offer_stays_usable_until_its_limit():
    discount = _discount(usage_limit=3)
    DiscountService.consume(MagicMock(), discount)
    assert discount.usage_count == 1
    assert discount.status == DiscountStatus.ACCEPTED
    DiscountService.consume(MagicMock(), discount)
    DiscountService.consume(MagicMock(), discount)
    assert discount.status == DiscountStatus.USED


def test_consume_does_not_commit_on_its_own():
    """It runs inside the checkout transaction. Committing here would spend
    the offer even if the order it was for never got created."""
    session = MagicMock()
    DiscountService.consume(session, _discount())
    session.commit.assert_not_called()


# --- how checkout resolves it ----------------------------------------------


def _items(seller_account_id=7):
    return [SimpleNamespace(product=SimpleNamespace(seller_id=seller_account_id))]


def _resolve(discount_id, items, *, seller_user_id=SELLER, subtotal=5000.0):
    session = MagicMock()
    session.get.return_value = SimpleNamespace(user_id=seller_user_id)
    with patch.object(
        DiscountService,
        "validate_for_order",
        return_value=(_discount(), 500.0, "ok"),
    ) as validate:
        result = CartService._resolve_chat_discount(
            session,
            user=SimpleNamespace(id=BUYER),
            discount_id=discount_id,
            items=items,
            subtotal=subtotal,
            coupon_code=None,
        )
    return result, validate


def test_checkout_without_an_offer_falls_back_to_the_coupon_path():
    (amount, discount), validate = _resolve(None, _items())
    assert discount is None
    assert amount == 0  # no coupon system yet; the stub returns nothing
    validate.assert_not_called()


def test_checkout_scopes_the_offer_to_the_shop_being_bought_from():
    """The shop comes from the items, not from the seller_id the client sent
    -- it is that shop's money, and it is known even when the client sent no
    seller_id at all."""
    (amount, discount), validate = _resolve(1, _items())
    assert discount is not None
    assert amount == 500
    assert validate.call_args.kwargs["seller_user_id"] == SELLER


def test_a_shop_that_cannot_be_named_is_refused_rather_than_left_unscoped():
    """Two shops in one payload should be impossible by the time we get here.
    If it ever is not, the offer is refused -- an unscoped check is the exact
    hole the scoping closes."""
    items = _items(7) + _items(9)
    with pytest.raises(ValidationError):
        _resolve(1, items)


def test_an_item_with_no_product_row_cannot_smuggle_the_offer_through():
    items = [SimpleNamespace(product=None)]
    with pytest.raises(ValidationError):
        _resolve(1, items)


def test_a_refused_offer_stops_checkout_instead_of_charging_full_price():
    """Silently ignoring it would charge a buyer who chose an offer the full
    amount without telling them."""
    session = MagicMock()
    session.get.return_value = SimpleNamespace(user_id=SELLER)
    with patch.object(
        DiscountService,
        "validate_for_order",
        return_value=(None, 0.0, "Discount has expired"),
    ):
        with pytest.raises(ValidationError) as excinfo:
            CartService._resolve_chat_discount(
                session,
                user=SimpleNamespace(id=BUYER),
                discount_id=1,
                items=_items(),
                subtotal=5000.0,
                coupon_code=None,
            )
    # .message, not str(): APIError carries its text there.
    assert "expired" in excinfo.value.message.lower()
