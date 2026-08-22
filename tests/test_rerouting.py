"""Unit tests for the rerouting engine's candidate-seller lookup, hard
eligibility filter (§7.1-7.2), and the attempt loop (§7.1 steps 3-9)."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.fulfilment.models import FulfilmentAllocation, FulfilmentAllocationStatus
from app.orders.models import FulfilmentPreference
from app.fulfilment.rerouting import (
    FULFILMENT_DEADLINE_MINUTES,
    MAX_REROUTE_ATTEMPTS,
    PRICE_HEADROOM_RATE,
    ReroutingService,
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
        product_id="PRD_1",
        price=1000.0,
        quantity=2,
        variant_id=None,
        seller_id=7,
        fulfilment_preference=FulfilmentPreference.AUTO,
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

    assert result is None
    assert failed.status == FulfilmentAllocationStatus.ACCEPTED


@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_starts_from_buyer_rejected(mock_scope):
    """§6.1: a buyer-rejected substitution can be retried like any other
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
    # returning None immediately for being off DECLINED/TIMEOUT -- proves
    # BUYER_REJECTED is accepted as a valid starting status.
    assert result is None
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED


@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_seller_only_skips_straight_to_unfulfilled(mock_scope):
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

    assert result is None
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED
    # Never got as far as computing the deadline/retry-limit or looking up
    # candidates -- SELLER_ONLY short-circuits before any of that.
    fa_mock.filter_by.assert_not_called()


@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_marks_unfulfilled_past_deadline(mock_scope):
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
    fa_mock.filter_by.return_value.count.return_value = 1

    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        fa_mock, oi_mock, MagicMock(), MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    result = ReroutingService.attempt_reroute(1)

    assert result is None
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED


@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_marks_unfulfilled_past_retry_limit(mock_scope):
    failed = _failed_allocation(FulfilmentAllocationStatus.TIMEOUT)
    order_item = _order_item()
    first_attempt = SimpleNamespace(created_at=datetime.utcnow())

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    fa_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        first_attempt
    )
    fa_mock.filter_by.return_value.count.return_value = MAX_REROUTE_ATTEMPTS

    oi_mock = MagicMock()
    oi_mock.get.return_value = order_item

    session = MagicMock()
    session.query.side_effect = _query_side_effect(
        fa_mock, oi_mock, MagicMock(), MagicMock()
    )
    mock_scope.return_value.__enter__.return_value = session

    result = ReroutingService.attempt_reroute(1)

    assert result is None
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED


@patch("app.fulfilment.rerouting.filter_eligible_candidates")
@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_marks_unfulfilled_when_no_eligible_candidates(
    mock_scope, mock_filter
):
    failed = _failed_allocation(FulfilmentAllocationStatus.DECLINED)
    order_item = _order_item()
    first_attempt = SimpleNamespace(created_at=datetime.utcnow())

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    fa_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        first_attempt
    )
    fa_mock.filter_by.return_value.count.return_value = 1

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

    assert result is None
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED


@patch("app.fulfilment.services.FulfilmentService.create_allocation")
@patch("app.inventory.services.InventoryService.reserve_stock")
@patch("app.fulfilment.ranking.rank_candidates")
@patch("app.fulfilment.rerouting.filter_eligible_candidates")
@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_reserves_top_ranked_candidate(
    mock_scope, mock_filter, mock_rank, mock_reserve, mock_create
):
    failed = _failed_allocation(FulfilmentAllocationStatus.DECLINED)
    order_item = _order_item()
    first_attempt = SimpleNamespace(created_at=datetime.utcnow())

    fa_mock = MagicMock()
    fa_mock.get.return_value = failed
    fa_mock.filter_by.return_value.order_by.return_value.first.return_value = (
        first_attempt
    )
    fa_mock.filter_by.return_value.count.return_value = 1

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
    mock_reserve.return_value = SimpleNamespace(id="RSV_9")
    mock_create.return_value = SimpleNamespace(id=200)

    result = ReroutingService.attempt_reroute(1)

    assert result is mock_create.return_value
    mock_reserve.assert_called_once_with("PRD_2", "BYR_1", 2)
    mock_create.assert_called_once_with(
        10, "SLR_2", 2, product_id="PRD_2", reservation_id="RSV_9"
    )


@patch("app.fulfilment.services.FulfilmentService.create_allocation")
@patch("app.inventory.services.InventoryService.reserve_stock")
@patch("app.fulfilment.ranking.rank_candidates")
@patch("app.fulfilment.rerouting.filter_eligible_candidates")
@patch("app.fulfilment.rerouting.session_scope")
def test_attempt_reroute_marks_unfulfilled_when_every_candidate_loses_race(
    mock_scope, mock_filter, mock_rank, mock_reserve, mock_create
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
    fa_mock.filter_by.return_value.count.return_value = 1

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
    mock_reserve.side_effect = ConflictError("lost the race")

    result = ReroutingService.attempt_reroute(1)

    assert result is None
    mock_create.assert_not_called()
    assert failed.status == FulfilmentAllocationStatus.UNFULFILLED
