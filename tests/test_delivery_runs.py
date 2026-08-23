"""Unit tests for DeliveryRunService: batching, capacity, and cutoff
pricing (10.1-10.4)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.deliveries.models import DeliveryRun, DeliveryRunStatus
from app.deliveries.runs import (
    DEFAULT_BASE_PRICE,
    RUN_MAX_PACKAGES,
    RUN_MAX_WEIGHT_GRAMS,
    DeliveryRunService,
)
from app.fulfilment.models import FulfilmentAllocationStatus
from app.orders.models import OrderItem


# --- get_or_create_open_run ------------------------------------------


def test_get_or_create_open_run_creates_new_when_none_exist():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = (
        []
    )
    session.add.side_effect = lambda obj: setattr(obj, "id", "RUN_NEW01")

    run = DeliveryRunService.get_or_create_open_run(session, market_id=1, area_id=2)

    assert run.market_id == 1
    assert run.area_id == 2
    assert run.status == DeliveryRunStatus.OPEN
    assert run.max_packages == RUN_MAX_PACKAGES
    assert run.max_weight_grams == RUN_MAX_WEIGHT_GRAMS
    session.add.assert_called_once()


def test_get_or_create_open_run_returns_existing_under_capacity():
    existing_run = SimpleNamespace(id="RUN_1", max_packages=30)
    session = MagicMock()

    def query_side_effect(model):
        m = MagicMock()
        if model is DeliveryRun:
            m.filter_by.return_value.order_by.return_value.all.return_value = [
                existing_run
            ]
        else:
            m.filter_by.return_value.count.return_value = 5
        return m

    session.query.side_effect = query_side_effect

    run = DeliveryRunService.get_or_create_open_run(session, market_id=1, area_id=2)

    assert run is existing_run
    session.add.assert_not_called()


def test_get_or_create_open_run_creates_new_when_existing_is_full():
    full_run = SimpleNamespace(id="RUN_1", max_packages=30)
    session = MagicMock()

    def query_side_effect(model):
        m = MagicMock()
        if model is DeliveryRun:
            m.filter_by.return_value.order_by.return_value.all.return_value = [full_run]
        else:
            m.filter_by.return_value.count.return_value = 30
        return m

    session.query.side_effect = query_side_effect
    session.add.side_effect = lambda obj: setattr(obj, "id", "RUN_NEW01")

    run = DeliveryRunService.get_or_create_open_run(session, market_id=1, area_id=2)

    assert run is not full_run
    assert run.market_id == 1
    session.add.assert_called_once()


# --- _order_is_ready ----------------------------------------------------


def test_order_is_ready_true_when_all_items_accepted_or_preparing():
    item1 = SimpleNamespace(id=1, status=OrderItem.Status.PROCESSING)
    item2 = SimpleNamespace(id=2, status=OrderItem.Status.PROCESSING)
    order = SimpleNamespace(items=[item1, item2])
    alloc1 = SimpleNamespace(status=FulfilmentAllocationStatus.ACCEPTED)
    alloc2 = SimpleNamespace(status=FulfilmentAllocationStatus.PREPARING)

    session = MagicMock()
    session.query.return_value.filter_by.return_value.order_by.return_value.first.side_effect = [
        alloc1,
        alloc2,
    ]

    assert DeliveryRunService._order_is_ready(session, order) is True


def test_order_is_ready_false_when_item_missing_allocation():
    item1 = SimpleNamespace(id=1, status=OrderItem.Status.PROCESSING)
    order = SimpleNamespace(items=[item1])
    session = MagicMock()
    session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = (
        None
    )

    assert DeliveryRunService._order_is_ready(session, order) is False


def test_order_is_ready_false_when_item_still_awaiting_seller():
    item1 = SimpleNamespace(id=1, status=OrderItem.Status.PROCESSING)
    order = SimpleNamespace(items=[item1])
    alloc = SimpleNamespace(status=FulfilmentAllocationStatus.AWAITING_SELLER)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = (
        alloc
    )

    assert DeliveryRunService._order_is_ready(session, order) is False


def test_order_is_ready_false_when_every_item_cancelled():
    cancelled_item = SimpleNamespace(id=1, status=OrderItem.Status.CANCELLED)
    order = SimpleNamespace(items=[cancelled_item])
    session = MagicMock()

    assert DeliveryRunService._order_is_ready(session, order) is False


# --- _resolve_single_market ----------------------------------------------


def test_resolve_single_market_returns_market_when_all_items_share_one():
    item1 = SimpleNamespace(id=1, status=OrderItem.Status.PROCESSING, seller_id=10)
    item2 = SimpleNamespace(id=2, status=OrderItem.Status.PROCESSING, seller_id=11)
    order = SimpleNamespace(items=[item1, item2])
    seller1 = SimpleNamespace(market_id=5)
    seller2 = SimpleNamespace(market_id=5)
    session = MagicMock()
    session.query.return_value.get.side_effect = [seller1, seller2]

    assert DeliveryRunService._resolve_single_market(session, order) == 5


def test_resolve_single_market_returns_none_when_items_span_markets():
    item1 = SimpleNamespace(id=1, status=OrderItem.Status.PROCESSING, seller_id=10)
    item2 = SimpleNamespace(id=2, status=OrderItem.Status.PROCESSING, seller_id=11)
    order = SimpleNamespace(items=[item1, item2])
    seller1 = SimpleNamespace(market_id=5)
    seller2 = SimpleNamespace(market_id=6)
    session = MagicMock()
    session.query.return_value.get.side_effect = [seller1, seller2]

    assert DeliveryRunService._resolve_single_market(session, order) is None


def test_resolve_single_market_returns_none_when_seller_has_no_market():
    item1 = SimpleNamespace(id=1, status=OrderItem.Status.PROCESSING, seller_id=10)
    order = SimpleNamespace(items=[item1])
    seller1 = SimpleNamespace(market_id=None)
    session = MagicMock()
    session.query.return_value.get.side_effect = [seller1]

    assert DeliveryRunService._resolve_single_market(session, order) is None


# --- _order_weight_grams --------------------------------------------------


def test_order_weight_grams_sums_active_items_only():
    item1 = SimpleNamespace(
        id=1, status=OrderItem.Status.PROCESSING, product_id="P1", quantity=2
    )
    item2 = SimpleNamespace(
        id=2, status=OrderItem.Status.CANCELLED, product_id="P2", quantity=5
    )
    product1 = SimpleNamespace(weight=100.0)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.all.return_value = [
        item1,
        item2,
    ]
    session.query.return_value.get.return_value = product1

    total = DeliveryRunService._order_weight_grams(session, "ORD_1")

    assert total == 200.0


# --- close_runs_past_cutoff ------------------------------------------------


@patch("app.deliveries.runs.session_scope")
def test_close_runs_past_cutoff_cancels_empty_run(mock_scope):
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.OPEN)
    run.transition_to = lambda new_status, _r=run: DeliveryRun.transition_to(
        _r, new_status
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [run]
    session.query.return_value.filter_by.return_value.count.return_value = 0
    mock_scope.return_value.__enter__.return_value = session

    result = DeliveryRunService.close_runs_past_cutoff()

    assert result == {"closed": 0, "cancelled_empty": 1}
    assert run.status == DeliveryRunStatus.CANCELLED
    assert run.cancel_reason == "No orders joined before cutoff"


@patch("app.deliveries.runs.session_scope")
def test_close_runs_past_cutoff_prices_and_plans_nonempty_run(mock_scope):
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.OPEN)
    run.transition_to = lambda new_status, _r=run: DeliveryRun.transition_to(
        _r, new_status
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [run]
    session.query.return_value.filter_by.return_value.count.return_value = 4
    mock_scope.return_value.__enter__.return_value = session

    result = DeliveryRunService.close_runs_past_cutoff()

    assert result == {"closed": 1, "cancelled_empty": 0}
    assert run.status == DeliveryRunStatus.PLANNING
    assert run.base_price == DEFAULT_BASE_PRICE
    assert run.price_per_order == round(DEFAULT_BASE_PRICE / 4, 2)


# --- attach_eligible_orders ------------------------------------------------


@patch("app.deliveries.runs.DeliveryRunService.get_or_create_open_run")
@patch("app.deliveries.runs.DeliveryRunService._order_weight_grams")
@patch("app.deliveries.runs.DeliveryRunService._resolve_single_market")
@patch("app.deliveries.runs.DeliveryRunService._order_is_ready")
@patch("app.deliveries.runs.session_scope")
def test_attach_eligible_orders_attaches_ready_order(
    mock_scope, mock_ready, mock_market, mock_weight, mock_get_run
):
    shipping_address = SimpleNamespace(area_id=7)
    order = SimpleNamespace(id="ORD_1", items=[], shipping_address=shipping_address)
    run = SimpleNamespace(id="RUN_1", max_weight_grams=50000, run_orders=[])

    session = MagicMock()
    session.query.return_value.all.return_value = []
    session.query.return_value.join.return_value.filter.return_value.all.return_value = [
        order
    ]
    mock_scope.return_value.__enter__.return_value = session

    mock_ready.return_value = True
    mock_market.return_value = 3
    mock_weight.return_value = 100.0
    mock_get_run.return_value = run

    result = DeliveryRunService.attach_eligible_orders()

    assert result == {"attached": 1, "skipped_unresolved": 0}
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.delivery_run_id == "RUN_1"
    assert added.order_id == "ORD_1"


@patch("app.deliveries.runs.DeliveryRunService._create_open_run")
@patch("app.deliveries.runs.DeliveryRunService.get_or_create_open_run")
@patch("app.deliveries.runs.DeliveryRunService._order_weight_grams")
@patch("app.deliveries.runs.DeliveryRunService._resolve_single_market")
@patch("app.deliveries.runs.DeliveryRunService._order_is_ready")
@patch("app.deliveries.runs.session_scope")
def test_attach_eligible_orders_rolls_to_new_run_on_weight_overflow(
    mock_scope, mock_ready, mock_market, mock_weight, mock_get_run, mock_create_run
):
    shipping_address = SimpleNamespace(area_id=7)
    order = SimpleNamespace(id="ORD_1", items=[], shipping_address=shipping_address)
    existing_run_order = SimpleNamespace(order_id="ORD_OTHER")
    full_run = SimpleNamespace(
        id="RUN_FULL", max_weight_grams=1000, run_orders=[existing_run_order]
    )
    new_run = SimpleNamespace(id="RUN_NEW", max_weight_grams=50000, run_orders=[])

    session = MagicMock()
    session.query.return_value.all.return_value = []
    session.query.return_value.join.return_value.filter.return_value.all.return_value = [
        order
    ]
    mock_scope.return_value.__enter__.return_value = session

    mock_ready.return_value = True
    mock_market.return_value = 3
    # Call order: this order's own weight first, then each existing
    # run_order's weight while summing current_weight.
    mock_weight.side_effect = [600.0, 900.0]
    mock_get_run.return_value = full_run
    mock_create_run.return_value = new_run

    result = DeliveryRunService.attach_eligible_orders()

    assert result == {"attached": 1, "skipped_unresolved": 0}
    mock_create_run.assert_called_once_with(session, 3, 7)
    added = session.add.call_args[0][0]
    assert added.delivery_run_id == "RUN_NEW"


@patch("app.deliveries.runs.DeliveryRunService._resolve_single_market")
@patch("app.deliveries.runs.DeliveryRunService._order_is_ready")
@patch("app.deliveries.runs.session_scope")
def test_attach_eligible_orders_skips_when_market_unresolved(
    mock_scope, mock_ready, mock_market
):
    shipping_address = SimpleNamespace(area_id=7)
    order = SimpleNamespace(id="ORD_1", items=[], shipping_address=shipping_address)
    session = MagicMock()
    session.query.return_value.all.return_value = []
    session.query.return_value.join.return_value.filter.return_value.all.return_value = [
        order
    ]
    mock_scope.return_value.__enter__.return_value = session

    mock_ready.return_value = True
    mock_market.return_value = None

    result = DeliveryRunService.attach_eligible_orders()

    assert result == {"attached": 0, "skipped_unresolved": 1}
    session.add.assert_not_called()


@patch("app.deliveries.runs.DeliveryRunService._order_is_ready")
@patch("app.deliveries.runs.session_scope")
def test_attach_eligible_orders_skips_when_not_ready(mock_scope, mock_ready):
    order = SimpleNamespace(
        id="ORD_1", items=[], shipping_address=SimpleNamespace(area_id=7)
    )
    session = MagicMock()
    session.query.return_value.all.return_value = []
    session.query.return_value.join.return_value.filter.return_value.all.return_value = [
        order
    ]
    mock_scope.return_value.__enter__.return_value = session

    mock_ready.return_value = False

    result = DeliveryRunService.attach_eligible_orders()

    assert result == {"attached": 0, "skipped_unresolved": 0}
    session.add.assert_not_called()
