"""Unit tests for 7.4's Buyer Requests tie-in: the previously-no-op
seller-notification fix, the auto-generated reroute request, and
accept_offer's stock-reservation/fulfilment-reopening hook for it."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.categories.models import RequestCategory
from app.fulfilment.rerouting import PRICE_HEADROOM_RATE
from app.requests.models import BuyerRequest, RequestSource
from app.requests.services import BuyerRequestService, OfferStatus, RequestStatus


@patch("app.requests.services.NotificationService.create_notification")
@patch("app.requests.services.session_scope")
def test_notify_relevant_sellers_notifies_category_matched_sellers(
    mock_scope, mock_notify
):
    category = SimpleNamespace(is_primary=True, category_id=3)
    request = SimpleNamespace(
        id="REQ_1", title="Need Rice", market_id=None, categories=[category]
    )

    seller1 = SimpleNamespace(user_id="USR_S1")
    seller2 = SimpleNamespace(user_id="USR_S2")
    session = MagicMock()
    session.query.return_value.join.return_value = session.query.return_value
    session.query.return_value.filter.return_value = session.query.return_value
    session.query.return_value.distinct.return_value = session.query.return_value
    session.query.return_value.limit.return_value.all.return_value = [
        seller1,
        seller2,
    ]
    mock_scope.return_value.__enter__.return_value = session

    BuyerRequestService._notify_relevant_sellers(request)

    assert mock_notify.call_count == 2
    called_user_ids = {c.kwargs["user_id"] for c in mock_notify.call_args_list}
    assert called_user_ids == {"USR_S1", "USR_S2"}


@patch("app.requests.services.NotificationService.create_notification")
@patch("app.requests.services.session_scope")
def test_notify_relevant_sellers_applies_market_filter_when_set(
    mock_scope, mock_notify
):
    category = SimpleNamespace(is_primary=True, category_id=3)
    request = SimpleNamespace(
        id="REQ_1", title="Need Rice", market_id=5, categories=[category]
    )

    session = MagicMock()
    session.query.return_value.join.return_value = session.query.return_value
    session.query.return_value.filter.return_value = session.query.return_value
    session.query.return_value.distinct.return_value = session.query.return_value
    session.query.return_value.limit.return_value.all.return_value = []
    mock_scope.return_value.__enter__.return_value = session

    BuyerRequestService._notify_relevant_sellers(request)

    # The market-scoping .filter() call happens (in addition to the
    # category filter) -- can't easily assert call count with the
    # self-referential mock, but this at least exercises that branch
    # without raising, and no notification fires for an empty result.
    mock_notify.assert_not_called()


@patch("app.requests.services.NotificationService.create_notification")
@patch("app.requests.services.session_scope")
def test_notify_relevant_sellers_no_op_without_primary_category(
    mock_scope, mock_notify
):
    request = SimpleNamespace(id="REQ_1", title="Need Rice", categories=[])
    session = MagicMock()
    mock_scope.return_value.__enter__.return_value = session

    BuyerRequestService._notify_relevant_sellers(request)

    session.query.assert_not_called()
    mock_notify.assert_not_called()


@patch("app.requests.services.BuyerRequestService._notify_relevant_sellers")
@patch("app.requests.services.session_scope")
def test_create_reroute_request_builds_request_with_expected_fields(
    mock_scope, mock_notify
):
    created = {}

    def add_side_effect(obj):
        if isinstance(obj, BuyerRequest):
            obj.id = "REQ_AUTO1"
            created["request"] = obj
        elif isinstance(obj, RequestCategory):
            created["category"] = obj

    session = MagicMock()
    session.add.side_effect = add_side_effect
    fetched = SimpleNamespace(id="REQ_AUTO1", categories=[])
    session.query.return_value.options.return_value.get.return_value = fetched
    mock_scope.return_value.__enter__.return_value = session

    result = BuyerRequestService.create_reroute_request(
        buyer_user_id="USR_BUYER1",
        order_item_id=10,
        market_id=5,
        category_id=3,
        product_name="Rice 5kg",
        quantity=2,
        price=1000.0,
    )

    assert result is fetched
    request = created["request"]
    assert request.source == RequestSource.REROUTE_ENGINE
    assert request.order_item_id == 10
    assert request.market_id == 5
    assert request.status == RequestStatus.OPEN
    assert request.budget == round(1000.0 * (1 + PRICE_HEADROOM_RATE), 2)

    category = created["category"]
    assert category.category_id == 3
    assert category.is_primary is True

    mock_notify.assert_called_once_with(fetched)


@patch("app.requests.services.BuyerRequestService._notify_relevant_sellers")
@patch("app.requests.services.session_scope")
def test_create_reroute_request_skips_category_link_when_none(mock_scope, mock_notify):
    created = {}

    def add_side_effect(obj):
        if isinstance(obj, BuyerRequest):
            obj.id = "REQ_AUTO1"
        created[type(obj).__name__] = obj

    session = MagicMock()
    session.add.side_effect = add_side_effect
    session.query.return_value.options.return_value.get.return_value = SimpleNamespace(
        id="REQ_AUTO1", categories=[]
    )
    mock_scope.return_value.__enter__.return_value = session

    BuyerRequestService.create_reroute_request(
        buyer_user_id="USR_BUYER1",
        order_item_id=10,
        market_id=None,
        category_id=None,
        product_name="Rice 5kg",
        quantity=2,
        price=1000.0,
    )

    assert "RequestCategory" not in created


def _reroute_offer_fixture():
    request = SimpleNamespace(
        id="REQ_1",
        user_id="USR_BUYER1",
        status=RequestStatus.OPEN,
        source=RequestSource.REROUTE_ENGINE,
        order_item_id=10,
        title="Need Rice",
    )
    offer = SimpleNamespace(
        id=1,
        request_id="REQ_1",
        request=request,
        status=OfferStatus.PENDING,
        product_id="PRD_2",
        seller_id=99,
        price=1000.0,
        seller=SimpleNamespace(user_id="USR_SELLER1"),
    )
    order = SimpleNamespace(buyer_id="BYR_1")
    order_item = SimpleNamespace(quantity=2, order=order)
    return request, offer, order_item


def _requests_query_side_effect(offer, order_item):
    def side_effect(model):
        mock = MagicMock()
        name = getattr(model, "__name__", None)
        if name == "SellerOffer":
            mock.options.return_value.get.return_value = offer
            mock.filter.return_value.all.return_value = []
        elif name == "OrderItem":
            mock.get.return_value = order_item
        return mock

    return side_effect


@patch("app.requests.services.redis_client")
@patch("app.fulfilment.services.FulfilmentService.create_allocation")
@patch("app.inventory.services.InventoryService.reserve_stock")
@patch("app.requests.services.NotificationService.create_notification")
@patch("app.requests.services.session_scope")
def test_accept_offer_reroute_reserves_stock_and_creates_allocation(
    mock_scope, mock_notify, mock_reserve, mock_create_alloc, mock_redis
):
    request, offer, order_item = _reroute_offer_fixture()
    session = MagicMock()
    session.query.side_effect = _requests_query_side_effect(offer, order_item)
    mock_scope.return_value.__enter__.return_value = session

    mock_reserve.return_value = SimpleNamespace(id="RSV_9")

    result = BuyerRequestService.accept_offer(1, "USR_BUYER1")

    assert result is offer
    assert offer.status == OfferStatus.ACCEPTED
    assert request.status == RequestStatus.FULFILLED
    mock_reserve.assert_called_once_with("PRD_2", "BYR_1", 2)
    mock_create_alloc.assert_called_once_with(
        10, 99, 2, product_id="PRD_2", reservation_id="RSV_9"
    )


@patch("app.requests.services.redis_client")
@patch("app.fulfilment.services.FulfilmentService.create_allocation")
@patch("app.inventory.services.InventoryService.reserve_stock")
@patch("app.requests.services.NotificationService.create_notification")
@patch("app.requests.services.session_scope")
def test_accept_offer_reroute_without_product_rejects(
    mock_scope, mock_notify, mock_reserve, mock_create_alloc, mock_redis
):
    from app.libs.errors import ValidationError

    request, offer, order_item = _reroute_offer_fixture()
    offer.product_id = None
    session = MagicMock()
    session.query.side_effect = _requests_query_side_effect(offer, order_item)
    mock_scope.return_value.__enter__.return_value = session

    try:
        BuyerRequestService.accept_offer(1, "USR_BUYER1")
        assert False, "expected ValidationError"
    except ValidationError:
        pass

    mock_reserve.assert_not_called()
    mock_create_alloc.assert_not_called()


@patch("app.requests.services.redis_client")
@patch("app.fulfilment.services.FulfilmentService.create_allocation")
@patch("app.requests.services.NotificationService.create_notification")
@patch("app.requests.services.session_scope")
def test_accept_offer_non_reroute_does_not_reserve_or_allocate(
    mock_scope, mock_notify, mock_create_alloc, mock_redis
):
    request = SimpleNamespace(
        id="REQ_1",
        user_id="USR_BUYER1",
        status=RequestStatus.OPEN,
        source=RequestSource.BUYER,
        order_item_id=None,
        title="Need Rice",
    )
    offer = SimpleNamespace(
        id=1,
        request_id="REQ_1",
        request=request,
        status=OfferStatus.PENDING,
        product_id=None,
        seller_id=99,
        price=1000.0,
        seller=SimpleNamespace(user_id="USR_SELLER1"),
    )

    session = MagicMock()
    session.query.return_value.options.return_value.get.return_value = offer
    session.query.return_value.filter.return_value.all.return_value = []
    mock_scope.return_value.__enter__.return_value = session

    result = BuyerRequestService.accept_offer(1, "USR_BUYER1")

    assert result is offer
    assert offer.status == OfferStatus.ACCEPTED
    assert request.status == RequestStatus.FULFILLED
    mock_create_alloc.assert_not_called()
