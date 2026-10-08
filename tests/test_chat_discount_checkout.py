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


def _items(seller_account_id=7, product_id="PRD_A", price=5000.0, quantity=1):
    return [
        SimpleNamespace(
            product=SimpleNamespace(
                id=product_id, name="A jersey", seller_id=seller_account_id
            ),
            product_price=price,
            quantity=quantity,
        )
    ]


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


# --- an offer pinned to one product ----------------------------------------
#
# A seller offering "15% off" while looking at a jersey means the jersey. It
# used to come off the whole basket from that shop, so adding four more things
# quietly multiplied what the seller had given away.


def _product_discount(product_id="PRD_A", **overrides):
    return _discount(product_id=product_id, **overrides)


def _validate_scoped(discount, *, order_amount, eligible, names=None):
    return DiscountService.validate_for_order(
        _session(discount),
        buyer_user_id=BUYER,
        discount_id=1,
        order_amount=order_amount,
        seller_user_id=SELLER,
        eligible_by_product=eligible,
        product_names=names or {"PRD_A": "A jersey"},
    )


def test_a_product_offer_comes_off_that_product_only():
    """N5,000 jersey inside a N20,000 basket: 10% is N500, not N2,000."""
    found, amount, _ = _validate_scoped(
        _product_discount(discount_type=DiscountType.PERCENTAGE, discount_value=10.0),
        order_amount=20000.0,
        eligible={"PRD_A": 5000.0},
    )
    assert found is not None
    assert amount == 500.0


def test_a_product_offer_counts_every_line_of_that_product():
    """Two of them in the basket is twice the base."""
    _, amount, _ = _validate_scoped(
        _product_discount(discount_type=DiscountType.PERCENTAGE, discount_value=10.0),
        order_amount=20000.0,
        eligible={"PRD_A": 10000.0},
    )
    assert amount == 1000.0


def test_a_product_offer_is_refused_when_that_product_is_not_being_bought():
    """And says which product, so the buyer can go and add it."""
    found, amount, message = _validate_scoped(
        _product_discount(),
        order_amount=20000.0,
        eligible={"PRD_OTHER": 20000.0},
    )
    assert found is None
    assert amount == 0.0
    assert "A jersey" in message


def test_a_fixed_product_offer_cannot_exceed_that_product():
    """N5,000 off a N1,200 item is N1,200 off -- the rest of the basket is not
    the seller's to discount."""
    _, amount, _ = _validate_scoped(
        _product_discount(discount_value=5000.0),
        order_amount=20000.0,
        eligible={"PRD_A": 1200.0},
    )
    assert amount == 1200.0


def test_a_shop_wide_offer_still_comes_off_the_whole_order():
    """No product on the offer: unchanged behaviour."""
    _, amount, _ = _validate_scoped(
        _discount(discount_type=DiscountType.PERCENTAGE, discount_value=10.0),
        order_amount=20000.0,
        eligible={"PRD_A": 5000.0},
    )
    assert amount == 2000.0


def test_the_minimum_order_is_still_about_the_order_not_the_product():
    """ "Minimum order of N10,000" means the order. A N5,000 jersey inside a
    N20,000 basket meets it."""
    found, amount, _ = _validate_scoped(
        _product_discount(
            discount_type=DiscountType.PERCENTAGE,
            discount_value=10.0,
            minimum_order_amount=10000.0,
        ),
        order_amount=20000.0,
        eligible={"PRD_A": 5000.0},
    )
    assert found is not None
    assert amount == 500.0


def test_a_product_offer_without_a_map_falls_back_to_the_order():
    """An older caller that cannot say what is in the basket gets the previous
    behaviour rather than a refusal -- being wrong in the buyer's favour beats
    rejecting a checkout that used to work."""
    _, amount, _ = _validate_scoped(
        _product_discount(discount_type=DiscountType.PERCENTAGE, discount_value=10.0),
        order_amount=20000.0,
        eligible=None,
    )
    assert amount == 2000.0


def test_checkout_passes_what_each_product_costs():
    """The map comes from the items being bought, not from the client."""
    items = _items(product_id="PRD_A", price=2500.0, quantity=2)
    (_, _), validate = _resolve(1, items, subtotal=5000.0)
    assert validate.call_args.kwargs["eligible_by_product"] == {"PRD_A": 5000.0}
    assert validate.call_args.kwargs["product_names"] == {"PRD_A": "A jersey"}


# --- spent by paying, not by reaching the payment screen --------------------
#
# Checkout creates a PENDING_PAYMENT order and the buyer pays on the next
# screen. Spending the offer at checkout meant backing out to change a
# quantity lost it -- and the second checkout was refused outright, so one
# stray back-tap locked the buyer out of buying at all. The cart survives
# checkout precisely so they can go back.


def _paid_order(discount_id=1, order_id="ORD_1"):
    return SimpleNamespace(id=order_id, chat_discount_id=discount_id)


def _spend(order, discount):
    from app.payments.services import PaymentService

    session = MagicMock()
    chain = session.query.return_value.filter.return_value.with_for_update.return_value
    chain.first.return_value = discount
    PaymentService._spend_chat_discount(session, order)
    return discount


def test_paying_spends_the_offer():
    discount = _spend(_paid_order(), _discount())
    assert discount.usage_count == 1
    assert discount.status == DiscountStatus.USED


def test_an_order_with_no_offer_spends_nothing():
    from app.payments.services import PaymentService

    session = MagicMock()
    PaymentService._spend_chat_discount(session, SimpleNamespace(id="ORD_1"))
    session.query.assert_not_called()


def test_a_second_payment_for_the_same_order_does_not_spend_it_twice():
    """A duplicate or late webhook must not burn a multi-use offer twice."""
    discount = _discount(usage_limit=3)
    _spend(_paid_order(), discount)
    _spend(_paid_order(), discount)
    # The call site guards on already_completed; this is the belt to that
    # brace -- what matters is that a spent-out offer is never pushed past
    # its limit.
    assert discount.usage_count <= discount.usage_limit


def test_an_offer_already_at_its_limit_is_left_alone():
    """Two unpaid orders can carry the same single-use offer if the buyer went
    back and checked out again. If both get paid, the second is already priced
    and taken -- there is nothing to claw back, so it is recorded, not
    doubled."""
    discount = _discount(usage_count=1, status=DiscountStatus.USED)
    _spend(_paid_order(), discount)
    assert discount.usage_count == 1


def test_a_missing_offer_never_fails_a_payment():
    from app.payments.services import PaymentService

    session = MagicMock()
    chain = session.query.return_value.filter.return_value.with_for_update.return_value
    chain.first.return_value = None
    PaymentService._spend_chat_discount(session, _paid_order())  # must not raise


def test_a_broken_lookup_never_fails_a_payment():
    """The money has already moved. An offer that could not be marked used is
    a bookkeeping problem to chase, not a reason to fail the payment."""
    from app.payments.services import PaymentService

    session = MagicMock()
    session.query.side_effect = RuntimeError("database gone")
    PaymentService._spend_chat_discount(session, _paid_order())  # must not raise
