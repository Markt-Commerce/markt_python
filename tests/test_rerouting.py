"""Unit tests for the rerouting engine's candidate-seller lookup, hard
eligibility filter (7.1-7.2), and the attempt loop (7.1 steps 3-9)."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.fulfilment.models import FulfilmentAllocation, FulfilmentAllocationStatus
from app.libs.errors import ForbiddenError, ValidationError
from app.notifications.models import NotificationType
from app.orders.models import FulfilmentPreference, OrderItem
from app.fulfilment.rerouting import (
    FULFILMENT_DEADLINE_MINUTES,
    MAX_REROUTE_ATTEMPTS,
    PRICE_HEADROOM_RATE,
    ReroutingService,
    escalate_unfulfilled_item,
    get_item_escalation,
    remove_escalated_item,
    _tokenize,
    filter_eligible_candidates,
    find_candidate_products,
)
from app.inventory.confidence import ConfidenceBand


def test_tokenize_strips_stopwords_short_tokens_and_punctuation():
    assert _tokenize("Rice, 5kg (Local)") == ["rice", "5kg", "local"]
    assert _tokenize("A Bag of Rice") == ["bag", "rice"]


def test_tokenize_empty_for_blank_name():
    assert _tokenize("") == []
    assert _tokenize(None) == []


def test_find_candidate_products_empty_when_no_keywords():
    session = MagicMock()
    product = SimpleNamespace(id="PRD_1", name="")

    result = find_candidate_products(session, product, exclude_seller_id=7)

    assert result == []
    session.query.assert_not_called()


def test_find_candidate_products_empty_when_no_primary_category():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    product = SimpleNamespace(id="PRD_1", name="Rice 5kg")

    result = find_candidate_products(session, product, exclude_seller_id=7)

    assert result == []


def test_find_candidate_products_empty_when_seller_has_no_market():
    session = MagicMock()
    category = SimpleNamespace(category_id=3)
    seller_no_market = SimpleNamespace(market_id=None)

    def query_side_effect(model):
        mock = MagicMock()
        name = getattr(model, "__name__", None)
        if name == "ProductCategory":
            mock.filter_by.return_value.first.return_value = category
        elif name == "Seller":
            mock.get.return_value = seller_no_market
        return mock

    session.query.side_effect = query_side_effect
    product = SimpleNamespace(id="PRD_1", name="Rice 5kg")

    result = find_candidate_products(session, product, exclude_seller_id=7)

    assert result == []


def test_find_candidate_products_returns_query_results_when_scoped():
    session = MagicMock()
    category = SimpleNamespace(category_id=3)
    seller = SimpleNamespace(market_id=5)
    expected = [SimpleNamespace(id="PRD_2")]

    def query_side_effect(model):
        mock = MagicMock()
        name = getattr(model, "__name__", None)
        if name == "ProductCategory":
            mock.filter_by.return_value.first.return_value = category
        elif name == "Seller":
            mock.get.return_value = seller
        elif name == "Product":
            # Chain every builder method back to the same mock so the
            # exact number of .filter() calls in the loop doesn't matter.
            mock.join.return_value = mock
            mock.outerjoin.return_value = mock
            mock.filter.return_value = mock
            mock.all.return_value = expected
        return mock

    session.query.side_effect = query_side_effect
    product = SimpleNamespace(id="PRD_1", name="Rice 5kg")

    result = find_candidate_products(session, product, exclude_seller_id=7)

    assert result == expected


@patch("app.fulfilment.rerouting.find_candidate_products")
@patch("app.fulfilment.rerouting.InventoryConfidenceService.get_band_for_product")
def test_filter_eligible_candidates_excludes_over_price_ceiling(mock_band, mock_find):
    session = MagicMock()
    within = SimpleNamespace(id="PRD_2", price=1040.0, variants=[])
    over = SimpleNamespace(id="PRD_3", price=1060.0, variants=[])
    mock_find.return_value = [within, over]
    mock_band.return_value = ConfidenceBand.HIGH

    original = SimpleNamespace(id="PRD_1", name="Rice 5kg")
    result = filter_eligible_candidates(session, original, 1000.0, exclude_seller_id=7)

    assert result == [within]
    assert within.price <= 1000.0 * (1 + PRICE_HEADROOM_RATE)
    # Regression guard: must pass the caller's already-open session
    # through rather than letting get_band_for_product open its own
    # nested session_scope() -- see test_inventory_confidence.py's own
    # regression test for the underlying bug this fixed.
    mock_band.assert_called_once_with(within.id, session=session)


@patch("app.fulfilment.rerouting.find_candidate_products")
@patch("app.fulfilment.rerouting.InventoryConfidenceService.get_band_for_product")
def test_filter_eligible_candidates_excludes_low_confidence(mock_band, mock_find):
    session = MagicMock()
    candidate = SimpleNamespace(id="PRD_2", price=1000.0, variants=[])
    mock_find.return_value = [candidate]
    mock_band.return_value = ConfidenceBand.LOW

    original = SimpleNamespace(id="PRD_1", name="Rice 5kg")
    result = filter_eligible_candidates(session, original, 1000.0, exclude_seller_id=7)

    assert result == []


@patch("app.fulfilment.rerouting.find_candidate_products")
@patch("app.fulfilment.rerouting.InventoryConfidenceService.get_band_for_product")
def test_filter_eligible_candidates_medium_confidence_is_eligible(mock_band, mock_find):
    session = MagicMock()
    candidate = SimpleNamespace(id="PRD_2", price=1000.0, variants=[])
    mock_find.return_value = [candidate]
    mock_band.return_value = ConfidenceBand.MEDIUM

    original = SimpleNamespace(id="PRD_1", name="Rice 5kg")
    result = filter_eligible_candidates(session, original, 1000.0, exclude_seller_id=7)

    assert result == [candidate]


@patch("app.fulfilment.rerouting.find_candidate_products")
def test_filter_eligible_candidates_excludes_variant_incompatible(mock_find):
    session = MagicMock()
    no_variants = SimpleNamespace(id="PRD_2", price=1000.0, variants=[])
    mock_find.return_value = [no_variants]

    original = SimpleNamespace(id="PRD_1", name="Rice 5kg")
    result = filter_eligible_candidates(
        session, original, 1000.0, exclude_seller_id=7, variant_id=9
    )

    assert result == []


def _failed_allocation(status, **overrides):
    defaults = dict(
        id=1,
        order_item_id=10,
        seller_id=7,
        created_at=datetime.utcnow() - timedelta(minutes=1),
    )
    defaults.update(overrides)
    a = SimpleNamespace(status=status, **defaults)
    a.transition_to = lambda new_status, _a=a: FulfilmentAllocation.transition_to(
        _a, new_status
    )
    return a


def _order_item(**overrides):
    defaults = dict(
        id=10,
        order_id="ORD_1",
        product_id="PRD_1",
        price=1000.0,
        quantity=2,
        variant_id=None,
        seller_id=7,
        fulfilment_preference=FulfilmentPreference.AUTO,
        allow_partial_quantity=True,
        order=SimpleNamespace(buyer_id="BYR_1"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _query_side_effect(fa_mock, oi_mock, seller_id_mock, product_mock):
    def side_effect(model):
        key = getattr(model, "key", None)
        name = getattr(model, "__name__", None)
        if key == "seller_id":
            return seller_id_mock
        if name == "FulfilmentAllocation":
            return fa_mock
        if name == "OrderItem":
            return oi_mock
        if name == "Product":
            return product_mock
        return MagicMock()

    return side_effect


@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_no_op_when_not_declined_or_timeout(mock_scope):
    failed = _failed_allocation(FulfilmentAllocationStatus.ACCEPTED)
    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        fa_mock, MagicMock(), MagicMock(), MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    result = ReroutingService.attempt_reroute(1)

    assert result == []
    assert failed.status == FulfilmentAllocationStatus.ACCEPTED


@patch("app.fulfilment.rerouting.escalate_unfulfilled_item")
@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_starts_from_buyer_rejected(mock_scope, mock_escalate):
    """6.1: a buyer-rejected substitution can be retried like any other
    failure, not just DECLINED/TIMEOUT."""
    failed = _failed_allocation(FulfilmentAllocationStatus.BUYER_REJECTED)
    order_item = _order_item(fulfilment_preference=FulfilmentPreference.SELLER_ONLY)

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed

    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        fa_mock, oi_mock, MagicMock(), MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    result = ReroutingService.attempt_reroute(1)

    # Routed through to the SELLER_ONLY short-circuit below rather than
    # returning [] immediately for being off DECLINED/TIMEOUT -- proves
    # BUYER_REJECTED is accepted as a valid starting status.
    assert result == []
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED
    # SELLER_ONLY must never escalate to Buyer Requests either -- the
    # buyer explicitly opted out of rerouting altogether.
    mock_escalate.assert_not_called()


@patch("app.fulfilment.rerouting.escalate_unfulfilled_item")
@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_seller_only_skips_straight_to_unfulfilled(
    mock_scope, mock_escalate
):
    failed = _failed_allocation(FulfilmentAllocationStatus.DECLINED)
    order_item = _order_item(fulfilment_preference=FulfilmentPreference.SELLER_ONLY)

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed

    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        fa_mock, oi_mock, MagicMock(), MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    result = ReroutingService.attempt_reroute(1)

    assert result == []
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED
    # Never got as far as computing the deadline/retry-limit or looking up
    # candidates -- SELLER_ONLY short-circuits before any of that.
    fa_mock.filter_by.assert_not_called()
    mock_escalate.assert_not_called()


@patch("app.fulfilment.rerouting.NotificationService.create_notification")
@patch("app.fulfilment.rerouting.escalate_unfulfilled_item")
@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_notifies_buyer_when_unfulfilled(
    mock_scope, mock_escalate, mock_notify
):
    """Phase 12 (15): "no replacement found" -- the buyer must be
    notified, not just have an event logged."""
    failed = _failed_allocation(FulfilmentAllocationStatus.DECLINED)
    order_item = _order_item(
        fulfilment_preference=FulfilmentPreference.SELLER_ONLY,
        order=SimpleNamespace(
            buyer=SimpleNamespace(user_id="USR_BUYER1"), buyer_id="BYR_1"
        ),
    )

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed

    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        fa_mock, oi_mock, MagicMock(), MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    ReroutingService.attempt_reroute(1)

    mock_notify.assert_called_once()
    call_kwargs = mock_notify.call_args.kwargs
    assert call_kwargs["user_id"] == "USR_BUYER1"
    assert call_kwargs["notification_type"] == NotificationType.ITEM_UNFULFILLED
    assert call_kwargs["reference_id"] == str(order_item.id)


@patch("app.fulfilment.rerouting.NotificationService.create_notification")
@patch("app.fulfilment.rerouting.escalate_unfulfilled_item")
@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_swallows_notification_failure(
    mock_scope, mock_escalate, mock_notify
):
    """A notification failure must never mask the UNFULFILLED transition
    that already happened."""
    failed = _failed_allocation(FulfilmentAllocationStatus.DECLINED)
    order_item = _order_item(
        fulfilment_preference=FulfilmentPreference.SELLER_ONLY,
        order=SimpleNamespace(
            buyer=SimpleNamespace(user_id="USR_BUYER1"), buyer_id="BYR_1"
        ),
    )
    mock_notify.side_effect = Exception("notification service down")

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed

    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        fa_mock, oi_mock, MagicMock(), MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    result = ReroutingService.attempt_reroute(1)

    assert result == []
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED


@patch("app.fulfilment.rerouting.escalate_unfulfilled_item")
@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_marks_unfulfilled_past_deadline(mock_scope, mock_escalate):
    failed = _failed_allocation(FulfilmentAllocationStatus.DECLINED)
    order_item = _order_item()
    first_attempt = SimpleNamespace(
        created_at=datetime.utcnow()
        - timedelta(minutes=FULFILMENT_DEADLINE_MINUTES + 1)
    )

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    fa_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        first_attempt
    )
    # No active siblings (5.1) -- nothing secured, so this is the plain
    # pre-5.1 "nothing at all secured" give-up path.
    fa_mock.filter.return_value.all.return_value = []

    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        fa_mock, oi_mock, MagicMock(), MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    result = ReroutingService.attempt_reroute(1)

    assert result == []
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED
    mock_escalate.assert_called_once_with(1)


@patch("app.fulfilment.rerouting.escalate_unfulfilled_item")
@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_marks_unfulfilled_past_retry_limit(mock_scope, mock_escalate):
    failed = _failed_allocation(FulfilmentAllocationStatus.TIMEOUT)
    order_item = _order_item()
    first_attempt = SimpleNamespace(created_at=datetime.utcnow())

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    fa_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        first_attempt
    )
    fa_mock.filter.return_value.count.return_value = MAX_REROUTE_ATTEMPTS
    fa_mock.filter.return_value.all.return_value = []

    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        fa_mock, oi_mock, MagicMock(), MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    result = ReroutingService.attempt_reroute(1)

    assert result == []
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED
    mock_escalate.assert_called_once_with(1)


@patch("app.fulfilment.rerouting.escalate_unfulfilled_item")
@patch("app.fulfilment.rerouting.filter_eligible_candidates")
@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_marks_unfulfilled_when_no_eligible_candidates(
    mock_scope, mock_filter, mock_escalate
):
    failed = _failed_allocation(FulfilmentAllocationStatus.DECLINED)
    order_item = _order_item()
    first_attempt = SimpleNamespace(created_at=datetime.utcnow())

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    fa_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        first_attempt
    )
    fa_mock.filter.return_value.count.return_value = 1
    fa_mock.filter.return_value.all.return_value = []

    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    product_mock = MagicMock()
    product_mock.get.return_value = SimpleNamespace(id="PRD_1", name="Rice 5kg")

    seller_id_mock = MagicMock()
    seller_id_mock.filter_by.return_value.all.return_value = [(7,)]

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        fa_mock, oi_mock, seller_id_mock, product_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    mock_filter.return_value = []

    result = ReroutingService.attempt_reroute(1)

    assert result == []
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED
    mock_escalate.assert_called_once_with(1)


@patch("app.inventory.services.InventoryService.get_available_quantity")
@patch("app.fulfilment.services.FulfilmentService.create_allocation")
@patch("app.inventory.services.InventoryService.reserve_stock")
@patch("app.fulfilment.ranking.rank_candidates")
@patch("app.fulfilment.rerouting.filter_eligible_candidates")
@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_reserves_top_ranked_candidate(
    mock_scope, mock_filter, mock_rank, mock_reserve, mock_create, mock_available
):
    failed = _failed_allocation(FulfilmentAllocationStatus.DECLINED)
    order_item = _order_item()
    first_attempt = SimpleNamespace(created_at=datetime.utcnow())

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    fa_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        first_attempt
    )
    fa_mock.filter.return_value.count.return_value = 1
    fa_mock.filter.return_value.all.return_value = []

    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    product_mock = MagicMock()
    product_mock.get.return_value = SimpleNamespace(id="PRD_1", name="Rice 5kg")

    seller_id_mock = MagicMock()
    seller_id_mock.filter_by.return_value.all.return_value = [(7,)]

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        fa_mock, oi_mock, seller_id_mock, product_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    mock_filter.return_value = [SimpleNamespace(id="PRD_2", seller_id="SLR_2")]
    mock_rank.return_value = [{"product_id": "PRD_2", "seller_id": "SLR_2"}]
    mock_available.return_value = 2  # covers the full shortfall alone
    mock_reserve.return_value = SimpleNamespace(id="RSV_9")
    mock_create.return_value = SimpleNamespace(id=200)

    result = ReroutingService.attempt_reroute(1)

    assert result == [mock_create.return_value]
    mock_reserve.assert_called_once_with("PRD_2", "BYR_1", 2)
    mock_create.assert_called_once_with(
        10, "SLR_2", 2, product_id="PRD_2", reservation_id="RSV_9"
    )


@patch("app.inventory.services.InventoryService.get_available_quantity")
@patch("app.fulfilment.rerouting.escalate_unfulfilled_item")
@patch("app.fulfilment.services.FulfilmentService.create_allocation")
@patch("app.inventory.services.InventoryService.reserve_stock")
@patch("app.fulfilment.ranking.rank_candidates")
@patch("app.fulfilment.rerouting.filter_eligible_candidates")
@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_marks_unfulfilled_when_every_candidate_loses_race(
    mock_scope,
    mock_filter,
    mock_rank,
    mock_reserve,
    mock_create,
    mock_escalate,
    mock_available,
):
    from app.libs.errors import ConflictError

    failed = _failed_allocation(FulfilmentAllocationStatus.DECLINED)
    order_item = _order_item()
    first_attempt = SimpleNamespace(created_at=datetime.utcnow())

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    fa_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        first_attempt
    )
    fa_mock.filter.return_value.count.return_value = 1
    fa_mock.filter.return_value.all.return_value = []

    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    product_mock = MagicMock()
    product_mock.get.return_value = SimpleNamespace(id="PRD_1", name="Rice 5kg")

    seller_id_mock = MagicMock()
    seller_id_mock.filter_by.return_value.all.return_value = [(7,)]

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        fa_mock, oi_mock, seller_id_mock, product_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    mock_filter.return_value = [SimpleNamespace(id="PRD_2", seller_id="SLR_2")]
    mock_rank.return_value = [{"product_id": "PRD_2", "seller_id": "SLR_2"}]
    mock_available.return_value = 2
    mock_reserve.side_effect = ConflictError("lost the race")

    result = ReroutingService.attempt_reroute(1)

    assert result == []
    mock_create.assert_not_called()
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED
    mock_escalate.assert_called_once_with(1)


def _escalate_query_side_effect(
    fa_mock, oi_mock, buyer_request_mock, product_mock, seller_mock, category_mock
):
    def side_effect(model):
        name = getattr(model, "__name__", None)
        return {
            "FulfilmentAllocation": fa_mock,
            "OrderItem": oi_mock,
            "BuyerRequest": buyer_request_mock,
            "Product": product_mock,
            "Seller": seller_mock,
            "ProductCategory": category_mock,
        }.get(name, MagicMock())

    return side_effect


@patch("app.requests.services.BuyerRequestService.create_reroute_request")
@patch("app.fulfilment.rerouting.session_scope")
def test_escalate_unfulfilled_item_creates_reroute_request(mock_scope, mock_create):
    failed = SimpleNamespace(
        status=FulfilmentAllocationStatus.UNFULFILLED, order_item_id=10
    )
    order_item = _order_item(
        order=SimpleNamespace(buyer=SimpleNamespace(user_id="USR_BUYER1"))
    )
    product = SimpleNamespace(id="PRD_1", name="Rice 5kg")
    seller = SimpleNamespace(market_id=5)
    category = SimpleNamespace(category_id=3)

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item
    buyer_request_mock = MagicMock()
    buyer_request_mock.filter_by.return_value.first.return_value = None
    product_mock = MagicMock()
    product_mock.get.return_value = product
    seller_mock = MagicMock()
    seller_mock.get.return_value = seller
    category_mock = MagicMock()
    category_mock.filter_by.return_value.first.return_value = category

    session = MagicMock()
    session.query.side_effect = _escalate_query_side_effect(
        fa_mock, oi_mock, buyer_request_mock, product_mock, seller_mock, category_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    escalate_unfulfilled_item(1)

    mock_create.assert_called_once_with(
        buyer_user_id="USR_BUYER1",
        order_item_id=10,
        market_id=5,
        category_id=3,
        product_name="Rice 5kg",
        quantity=2,
        price=1000.0,
    )


@patch("app.requests.services.BuyerRequestService.create_reroute_request")
@patch("app.fulfilment.rerouting.session_scope")
def test_escalate_unfulfilled_item_no_op_when_not_unfulfilled(mock_scope, mock_create):
    failed = SimpleNamespace(
        status=FulfilmentAllocationStatus.DECLINED, order_item_id=10
    )
    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    session = MagicMock()
    session.query.side_effect = _escalate_query_side_effect(
        fa_mock, MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    escalate_unfulfilled_item(1)

    mock_create.assert_not_called()


@patch("app.requests.services.BuyerRequestService.create_reroute_request")
@patch("app.fulfilment.rerouting.session_scope")
def test_escalate_unfulfilled_item_no_op_for_seller_only(mock_scope, mock_create):
    failed = SimpleNamespace(
        status=FulfilmentAllocationStatus.UNFULFILLED, order_item_id=10
    )
    order_item = _order_item(fulfilment_preference=FulfilmentPreference.SELLER_ONLY)

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    session = MagicMock()
    session.query.side_effect = _escalate_query_side_effect(
        fa_mock, oi_mock, MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    escalate_unfulfilled_item(1)

    mock_create.assert_not_called()


@patch("app.requests.services.BuyerRequestService.create_reroute_request")
@patch("app.fulfilment.rerouting.session_scope")
def test_escalate_unfulfilled_item_no_op_when_already_escalated(
    mock_scope, mock_create
):
    failed = SimpleNamespace(
        status=FulfilmentAllocationStatus.UNFULFILLED, order_item_id=10
    )
    order_item = _order_item()

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item
    buyer_request_mock = MagicMock()
    buyer_request_mock.filter_by.return_value.first.return_value = SimpleNamespace(
        id="REQ_EXISTING"
    )

    session = MagicMock()
    session.query.side_effect = _escalate_query_side_effect(
        fa_mock, oi_mock, buyer_request_mock, MagicMock(), MagicMock(), MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    escalate_unfulfilled_item(1)

    mock_create.assert_not_called()


@patch("app.requests.services.BuyerRequestService.create_reroute_request")
@patch("app.fulfilment.rerouting.session_scope")
def test_escalate_unfulfilled_item_swallows_exceptions(mock_scope, mock_create):
    mock_scope.side_effect = RuntimeError("db exploded")

    # Must not raise -- escalation failures are logged, not propagated.
    escalate_unfulfilled_item(1)

    mock_create.assert_not_called()


# ---- 7.3 escalation: get_item_escalation / remove_escalated_item ----


def _escalation_order_item(**overrides):
    defaults = dict(
        id=10,
        order_id="ORD_1",
        product_id="PRD_1",
        price=1000.0,
        quantity=2,
        status=OrderItem.Status.PROCESSING,
        order=SimpleNamespace(
            buyer_id="BYR_1", buyer=SimpleNamespace(user_id="USR_BUYER1")
        ),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _escalation_query_side_effect(order_item_mock, allocation_mock, request_mock=None):
    def side_effect(model):
        name = getattr(model, "__name__", None)
        if name == "OrderItem":
            return order_item_mock
        if name == "FulfilmentAllocation":
            return allocation_mock
        if name == "BuyerRequest" and request_mock is not None:
            return request_mock
        return MagicMock()

    return side_effect


@patch("app.fulfilment.rerouting.session_scope")
def test_get_item_escalation_forbidden_for_non_owner(mock_scope):
    order_item_mock = MagicMock()
    order_item_mock.options.return_value.get.return_value = _escalation_order_item()

    session = MagicMock()
    session.query.side_effect = _escalation_query_side_effect(
        order_item_mock, MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ForbiddenError):
        get_item_escalation(10, buyer_id="SOMEONE_ELSE")


@patch("app.fulfilment.rerouting.session_scope")
def test_get_item_escalation_not_escalated_when_allocation_not_unfulfilled(mock_scope):
    order_item_mock = MagicMock()
    order_item_mock.options.return_value.get.return_value = _escalation_order_item()

    allocation_mock = MagicMock()
    allocation_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        SimpleNamespace(status=FulfilmentAllocationStatus.ACCEPTED)
    )

    session = MagicMock()
    session.query.side_effect = _escalation_query_side_effect(
        order_item_mock, allocation_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    result = get_item_escalation(10, buyer_id="BYR_1")

    assert result["escalated"] is False
    assert result["reroute_request"] is None


@patch("app.fulfilment.rerouting.session_scope")
def test_get_item_escalation_returns_only_pending_offers(mock_scope):
    from app.requests.models import RequestStatus
    from app.requests.services import OfferStatus

    order_item_mock = MagicMock()
    order_item_mock.options.return_value.get.return_value = _escalation_order_item()

    allocation_mock = MagicMock()
    allocation_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        SimpleNamespace(status=FulfilmentAllocationStatus.UNFULFILLED)
    )

    pending_offer = SimpleNamespace(
        id=1,
        seller_id=99,
        seller=SimpleNamespace(shop_name="Rice Palace"),
        product_id="PRD_2",
        price=1050.0,
        message=None,
        status=OfferStatus.PENDING,
    )
    accepted_offer = SimpleNamespace(
        id=2,
        seller_id=100,
        seller=SimpleNamespace(shop_name="Another Shop"),
        product_id="PRD_3",
        price=1100.0,
        message=None,
        status=OfferStatus.ACCEPTED,
    )
    reroute_request = SimpleNamespace(
        id="REQ_1",
        status=RequestStatus.OPEN,
        expires_at=None,
        offers=[pending_offer, accepted_offer],
    )
    request_mock = MagicMock()
    request_mock.options.return_value.filter_by.return_value.order_by.return_value.first.return_value = (
        reroute_request
    )

    session = MagicMock()
    session.query.side_effect = _escalation_query_side_effect(
        order_item_mock, allocation_mock, request_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    result = get_item_escalation(10, buyer_id="BYR_1")

    assert result["escalated"] is True
    offer_ids = [o["id"] for o in result["reroute_request"]["offers"]]
    assert offer_ids == [1]


@patch("app.fulfilment.rerouting.session_scope")
def test_remove_escalated_item_raises_when_not_escalated(mock_scope):
    order_item_mock = MagicMock()
    order_item_mock.options.return_value.get.return_value = _escalation_order_item()

    allocation_mock = MagicMock()
    allocation_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        SimpleNamespace(status=FulfilmentAllocationStatus.DECLINED)
    )

    session = MagicMock()
    session.query.side_effect = _escalation_query_side_effect(
        order_item_mock, allocation_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ValidationError):
        remove_escalated_item(10, buyer_id="BYR_1")


@patch("app.requests.services.BuyerRequestService.update_request_status")
@patch("app.orders.services.OrderService.refund_unresolved_item")
@patch("app.fulfilment.rerouting.session_scope")
def test_remove_escalated_item_refunds_and_closes_reroute_request(
    mock_scope, mock_refund, mock_close
):
    from app.requests.models import RequestStatus

    order_item_mock = MagicMock()
    order_item_mock.options.return_value.get.return_value = _escalation_order_item()

    allocation_mock = MagicMock()
    allocation_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        SimpleNamespace(status=FulfilmentAllocationStatus.UNFULFILLED)
    )

    open_request_mock = MagicMock()
    open_request_mock.filter_by.return_value.first.return_value = SimpleNamespace(
        id="REQ_1"
    )

    session = MagicMock()
    session.query.side_effect = _escalation_query_side_effect(
        order_item_mock, allocation_mock, open_request_mock
    )
    mock_scope.return_value.__enter__.return_value = session

    result = remove_escalated_item(10, buyer_id="BYR_1", reason="changed my mind")

    mock_refund.assert_called_once_with(10, reason="changed my mind")
    mock_close.assert_called_once_with("REQ_1", "USR_BUYER1", RequestStatus.CLOSED)
    assert result == {"order_item_id": 10, "status": "removed"}
