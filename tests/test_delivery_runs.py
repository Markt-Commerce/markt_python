"""Unit tests for DeliveryRunService: batching, capacity, and cutoff
pricing (10.1-10.4)."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.deliveries.models import (
    DeliveryRun,
    DeliveryRunOrder,
    DeliveryRunStatus,
    DeliveryRunWaitChoice,
)
from app.deliveries.runs import (
    DEFAULT_BASE_PRICE,
    RUN_MAX_PACKAGES,
    RUN_MAX_WEIGHT_GRAMS,
    DeliveryRunService,
)
from app.fulfilment.models import FulfilmentAllocationStatus
from app.libs.errors import ForbiddenError, NotFoundError
from app.orders.models import OrderItem


# --- get_or_create_open_run ------------------------------------------


def test_get_or_create_open_run_creates_new_when_none_exist():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.order_by.return_value.with_for_update.return_value.all.return_value = (
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
            m.filter_by.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [
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
            m.filter_by.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [
                full_run
            ]
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


# --- calculate_surge_multiplier ---------------------------------------------


def test_calculate_surge_multiplier_is_one_with_no_concurrent_runs():
    run = SimpleNamespace(id="RUN_1", market_id=1, area_id=2)
    session = MagicMock()
    session.query.return_value.filter.return_value.count.return_value = 0

    assert DeliveryRunService.calculate_surge_multiplier(session, run) == 1.0


def test_calculate_surge_multiplier_scales_with_concurrent_runs():
    run = SimpleNamespace(id="RUN_1", market_id=1, area_id=2)
    session = MagicMock()
    session.query.return_value.filter.return_value.count.return_value = 2

    result = DeliveryRunService.calculate_surge_multiplier(session, run)

    assert result == pytest.approx(1.0 + 2 * 0.15)


def test_calculate_surge_multiplier_caps_at_maximum():
    run = SimpleNamespace(id="RUN_1", market_id=1, area_id=2)
    session = MagicMock()
    session.query.return_value.filter.return_value.count.return_value = 100

    assert DeliveryRunService.calculate_surge_multiplier(session, run) == 2.0


# --- close_runs_past_cutoff ------------------------------------------------


def _cutoff_query_side_effect(run, run_orders, concurrent_active_runs=0):
    def query_side_effect(*args):
        model = args[0]
        m = MagicMock()
        if model is DeliveryRun:
            m.filter.return_value.all.return_value = [run]
            # calculate_surge_multiplier's own count() query -- default
            # to "no other concurrent runs" (surge_multiplier == 1.0) so
            # existing tests' base_price assertions don't need to change.
            m.filter.return_value.count.return_value = concurrent_active_runs
        elif model is DeliveryRunOrder:
            m.filter_by.return_value.all.return_value = run_orders
            m.filter.return_value.delete.return_value = None
        else:
            # session.query(Order.id, Order.buyer_id)
            m.filter.return_value.all.return_value = [
                (ro.order_id, 1) for ro in run_orders
            ]
        return m

    return query_side_effect


@patch("app.deliveries.runs.session_scope")
def test_close_runs_past_cutoff_cancels_empty_run(mock_scope):
    run = SimpleNamespace(
        id="RUN_1", status=DeliveryRunStatus.OPEN, market_id=1, area_id=1
    )
    run.transition_to = lambda new_status, _r=run: DeliveryRun.transition_to(
        _r, new_status
    )
    session = MagicMock()
    session.query.side_effect = _cutoff_query_side_effect(run, [])
    mock_scope.return_value.__enter__.return_value = session

    result = DeliveryRunService.close_runs_past_cutoff()

    assert result == {"closed": 0, "cancelled_empty": 1, "free_cancellations": 0}
    assert run.status == DeliveryRunStatus.CANCELLED
    assert run.cancel_reason == "No orders joined before cutoff"


@patch("app.deliveries.runs.session_scope")
def test_close_runs_past_cutoff_prices_and_plans_nonempty_run(mock_scope):
    run = SimpleNamespace(
        id="RUN_1", status=DeliveryRunStatus.OPEN, market_id=1, area_id=1
    )
    run.transition_to = lambda new_status, _r=run: DeliveryRun.transition_to(
        _r, new_status
    )
    # 4 orders >= THIN_VOLUME_THRESHOLD (3) -- not thin, no fallback checks.
    run_orders = [
        SimpleNamespace(
            order_id=f"ORD_{i}",
            wait_choice=DeliveryRunWaitChoice.PENDING,
            fallback_consent=False,
        )
        for i in range(4)
    ]
    session = MagicMock()
    session.query.side_effect = _cutoff_query_side_effect(run, run_orders)
    mock_scope.return_value.__enter__.return_value = session

    result = DeliveryRunService.close_runs_past_cutoff()

    assert result == {"closed": 1, "cancelled_empty": 0, "free_cancellations": 0}
    assert run.status == DeliveryRunStatus.RIDER_ASSIGNMENT
    assert run.surge_multiplier == 1.0
    assert run.base_price == DEFAULT_BASE_PRICE
    assert run.price_per_order == round(DEFAULT_BASE_PRICE / 4, 2)


@patch("app.deliveries.runs.session_scope")
def test_close_runs_past_cutoff_applies_surge_multiplier(mock_scope):
    run = SimpleNamespace(
        id="RUN_1", status=DeliveryRunStatus.OPEN, market_id=1, area_id=1
    )
    run.transition_to = lambda new_status, _r=run: DeliveryRun.transition_to(
        _r, new_status
    )
    run_orders = [
        SimpleNamespace(
            order_id=f"ORD_{i}",
            wait_choice=DeliveryRunWaitChoice.PENDING,
            fallback_consent=False,
        )
        for i in range(4)
    ]
    session = MagicMock()
    # Two other concurrent active runs for the same market/area --
    # surge_multiplier = 1.0 + 2*0.15 = 1.3.
    session.query.side_effect = _cutoff_query_side_effect(
        run, run_orders, concurrent_active_runs=2
    )
    mock_scope.return_value.__enter__.return_value = session

    DeliveryRunService.close_runs_past_cutoff()

    assert run.surge_multiplier == pytest.approx(1.3)
    assert run.base_price == round(DEFAULT_BASE_PRICE * 1.3, 2)


@patch("app.orders.services.OrderService.cancel_order")
@patch("app.deliveries.runs.session_scope")
def test_close_runs_past_cutoff_free_cancels_unconsented_thin_orders(
    mock_scope, mock_cancel
):
    """10.3 wait-deadline fallback: still thin at cutoff, nobody
    consented -- both orders get a free cancellation and the run, left
    with nothing, is cancelled rather than planned."""
    run = SimpleNamespace(
        id="RUN_1", status=DeliveryRunStatus.OPEN, market_id=1, area_id=1
    )
    run.transition_to = lambda new_status, _r=run: DeliveryRun.transition_to(
        _r, new_status
    )
    run_orders = [
        SimpleNamespace(
            order_id="ORD_1",
            wait_choice=DeliveryRunWaitChoice.PENDING,
            fallback_consent=False,
        ),
        SimpleNamespace(
            order_id="ORD_2",
            wait_choice=DeliveryRunWaitChoice.WAIT,
            fallback_consent=False,
        ),
    ]
    session = MagicMock()
    session.query.side_effect = _cutoff_query_side_effect(run, run_orders)
    mock_scope.return_value.__enter__.return_value = session

    result = DeliveryRunService.close_runs_past_cutoff()

    assert result == {"closed": 0, "cancelled_empty": 1, "free_cancellations": 2}
    assert run.status == DeliveryRunStatus.CANCELLED
    assert run.cancel_reason == "All orders free-cancelled on wait-deadline fallback"
    assert mock_cancel.call_count == 2


@patch("app.orders.services.OrderService.cancel_order")
@patch("app.deliveries.runs.session_scope")
def test_close_runs_past_cutoff_keeps_consented_order_cancels_the_rest(
    mock_scope, mock_cancel
):
    """A PAY_NOW/consenting order survives the fallback and the run still
    plans -- priced against only the surviving order(s)."""
    run = SimpleNamespace(
        id="RUN_1", status=DeliveryRunStatus.OPEN, market_id=1, area_id=1
    )
    run.transition_to = lambda new_status, _r=run: DeliveryRun.transition_to(
        _r, new_status
    )
    run_orders = [
        SimpleNamespace(
            order_id="ORD_CONSENTED",
            wait_choice=DeliveryRunWaitChoice.PAY_NOW,
            fallback_consent=False,
        ),
        SimpleNamespace(
            order_id="ORD_UNCONSENTED",
            wait_choice=DeliveryRunWaitChoice.PENDING,
            fallback_consent=False,
        ),
    ]
    session = MagicMock()
    session.query.side_effect = _cutoff_query_side_effect(run, run_orders)
    mock_scope.return_value.__enter__.return_value = session

    result = DeliveryRunService.close_runs_past_cutoff()

    assert result == {"closed": 1, "cancelled_empty": 0, "free_cancellations": 1}
    assert run.status == DeliveryRunStatus.RIDER_ASSIGNMENT
    assert run.price_per_order == round(DEFAULT_BASE_PRICE / 1, 2)
    mock_cancel.assert_called_once()


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


# --- _tighten_cutoff_for_perishables ---------------------------------------


def test_tighten_cutoff_for_perishables_pulls_cutoff_in():
    item = SimpleNamespace(id=1, status=OrderItem.Status.PROCESSING, product_id="P1")
    order = SimpleNamespace(items=[item])
    run = SimpleNamespace(cutoff_at=datetime.utcnow() + timedelta(hours=2))
    handling = SimpleNamespace(max_dwell_minutes=30)

    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [handling]

    DeliveryRunService._tighten_cutoff_for_perishables(session, run, order)

    assert run.cutoff_at <= datetime.utcnow() + timedelta(minutes=31)


def test_tighten_cutoff_for_perishables_noop_when_looser_than_cutoff():
    item = SimpleNamespace(id=1, status=OrderItem.Status.PROCESSING, product_id="P1")
    order = SimpleNamespace(items=[item])
    original_cutoff = datetime.utcnow() + timedelta(minutes=10)
    run = SimpleNamespace(cutoff_at=original_cutoff)
    handling = SimpleNamespace(max_dwell_minutes=120)

    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [handling]

    DeliveryRunService._tighten_cutoff_for_perishables(session, run, order)

    assert run.cutoff_at == original_cutoff


def test_tighten_cutoff_for_perishables_noop_when_no_perishable_items():
    item = SimpleNamespace(id=1, status=OrderItem.Status.PROCESSING, product_id="P1")
    order = SimpleNamespace(items=[item])
    original_cutoff = datetime.utcnow() + timedelta(hours=2)
    run = SimpleNamespace(cutoff_at=original_cutoff)

    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []

    DeliveryRunService._tighten_cutoff_for_perishables(session, run, order)

    assert run.cutoff_at == original_cutoff


# --- notify_thin_volume_orders ----------------------------------------------


def _thin_volume_query_side_effect(run, run_orders, order=None):
    def query_side_effect(*args):
        model = args[0]
        m = MagicMock()
        if model is DeliveryRun:
            m.filter.return_value.all.return_value = [run]
        elif model is DeliveryRunOrder:
            m.filter_by.return_value.all.return_value = run_orders
        else:
            m.get.return_value = order
        return m

    return query_side_effect


@patch("app.deliveries.runs.NotificationService.create_notification")
@patch("app.deliveries.runs.session_scope")
def test_notify_thin_volume_orders_notifies_once(mock_scope, mock_notify):
    cutoff = datetime.utcnow() + timedelta(hours=1)
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.OPEN, cutoff_at=cutoff)
    run_order = SimpleNamespace(order_id="ORD_1", notified_thin_volume_at=None)
    order = SimpleNamespace(buyer=SimpleNamespace(user_id="USR_1"))

    session = MagicMock()
    session.query.side_effect = _thin_volume_query_side_effect(run, [run_order], order)
    mock_scope.return_value.__enter__.return_value = session

    result = DeliveryRunService.notify_thin_volume_orders()

    assert result == {"notified": 1}
    assert run_order.notified_thin_volume_at is not None
    mock_notify.assert_called_once()
    call_kwargs = mock_notify.call_args.kwargs
    assert call_kwargs["user_id"] == "USR_1"
    assert call_kwargs["reference_id"] == "ORD_1"


@patch("app.deliveries.runs.NotificationService.create_notification")
@patch("app.deliveries.runs.session_scope")
def test_notify_thin_volume_orders_skips_already_notified(mock_scope, mock_notify):
    run = SimpleNamespace(
        id="RUN_1", status=DeliveryRunStatus.OPEN, cutoff_at=datetime.utcnow()
    )
    run_order = SimpleNamespace(
        order_id="ORD_1", notified_thin_volume_at=datetime.utcnow()
    )

    session = MagicMock()
    session.query.side_effect = _thin_volume_query_side_effect(run, [run_order])
    mock_scope.return_value.__enter__.return_value = session

    result = DeliveryRunService.notify_thin_volume_orders()

    assert result == {"notified": 0}
    mock_notify.assert_not_called()


@patch("app.deliveries.runs.NotificationService.create_notification")
@patch("app.deliveries.runs.session_scope")
def test_notify_thin_volume_orders_skips_runs_at_or_above_threshold(
    mock_scope, mock_notify
):
    run = SimpleNamespace(
        id="RUN_1", status=DeliveryRunStatus.OPEN, cutoff_at=datetime.utcnow()
    )
    run_orders = [
        SimpleNamespace(order_id=f"ORD_{i}", notified_thin_volume_at=None)
        for i in range(3)
    ]

    session = MagicMock()
    session.query.side_effect = _thin_volume_query_side_effect(run, run_orders)
    mock_scope.return_value.__enter__.return_value = session

    result = DeliveryRunService.notify_thin_volume_orders()

    assert result == {"notified": 0}
    mock_notify.assert_not_called()


# --- set_wait_choice ---------------------------------------------------------


def _wait_choice_session(run_order, order):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = run_order
    session.query.return_value.get.return_value = order
    return session


def test_set_wait_choice_records_choice_and_consent():
    run_order = SimpleNamespace(
        order_id="ORD_1",
        wait_choice=DeliveryRunWaitChoice.PENDING,
        fallback_consent=False,
    )
    order = SimpleNamespace(id="ORD_1", buyer_id=42)
    session = _wait_choice_session(run_order, order)

    with patch("app.deliveries.runs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryRunService.set_wait_choice(
            "ORD_1", 42, DeliveryRunWaitChoice.WAIT, fallback_consent=True
        )

    assert result.wait_choice == DeliveryRunWaitChoice.WAIT
    assert result.fallback_consent is True


def test_set_wait_choice_drops_consent_for_pay_now():
    """fallback_consent is only meaningful alongside WAIT -- PAY_NOW
    doesn't need it (the buyer already opted straight into paying)."""
    run_order = SimpleNamespace(
        order_id="ORD_1",
        wait_choice=DeliveryRunWaitChoice.PENDING,
        fallback_consent=False,
    )
    order = SimpleNamespace(id="ORD_1", buyer_id=42)
    session = _wait_choice_session(run_order, order)

    with patch("app.deliveries.runs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryRunService.set_wait_choice(
            "ORD_1", 42, DeliveryRunWaitChoice.PAY_NOW, fallback_consent=True
        )

    assert result.wait_choice == DeliveryRunWaitChoice.PAY_NOW
    assert result.fallback_consent is False


def test_set_wait_choice_raises_not_found_when_order_not_attached():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    with patch("app.deliveries.runs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(NotFoundError):
            DeliveryRunService.set_wait_choice("ORD_1", 42, DeliveryRunWaitChoice.WAIT)


def test_set_wait_choice_raises_forbidden_for_wrong_buyer():
    run_order = SimpleNamespace(order_id="ORD_1")
    order = SimpleNamespace(id="ORD_1", buyer_id=99)
    session = _wait_choice_session(run_order, order)

    with patch("app.deliveries.runs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ForbiddenError):
            DeliveryRunService.set_wait_choice("ORD_1", 42, DeliveryRunWaitChoice.WAIT)
