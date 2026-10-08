"""A buyer request that passes its expiry date.

The background sweep rejected the pending offers and then left the request
OPEN, because only update_request_status ever assigned RequestStatus.EXPIRED
and the sweep does not go through it. The buyer was told nothing either:
REQUEST_EXPIRED had a template and a channel config and no emitter.
"""

import pytest

from app.notifications.models import NotificationType
from app.requests.models import RequestStatus
from app.requests.services import BuyerRequestService


class FakeOffer:
    def __init__(self):
        self.status = None
        self.seller = type("S", (), {"user_id": "USR_SELLER"})()


class FakeRequest:
    def __init__(self):
        self.id = "REQ_1"
        self.title = "Blue ankara, 6 yards"
        self.status = RequestStatus.OPEN
        self.buyer = type("B", (), {"user_id": "USR_BUYER"})()


class FakeSession:
    """Just enough to satisfy the offer lookup."""

    def __init__(self, offers):
        self._offers = offers

    def query(self, *args):
        return self

    def filter_by(self, **kwargs):
        return self

    def all(self):
        return self._offers


@pytest.fixture
def captured(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.notifications.services.NotificationService.create_notification",
        lambda **kw: calls.append(kw),
    )
    return calls


def test_the_request_actually_expires(captured):
    request = FakeRequest()
    BuyerRequestService._handle_request_expiration(request, FakeSession([]))
    assert request.status is RequestStatus.EXPIRED


def test_the_buyer_is_told(captured):
    request = FakeRequest()
    BuyerRequestService._handle_request_expiration(request, FakeSession([]))

    expired = [
        c
        for c in captured
        if c["notification_type"] is NotificationType.REQUEST_EXPIRED
    ]
    assert len(expired) == 1
    assert expired[0]["user_id"] == "USR_BUYER"
    assert expired[0]["metadata_"]["request_title"] == "Blue ankara, 6 yards"


def test_pending_offers_are_still_closed_out(captured):
    offer = FakeOffer()
    request = FakeRequest()
    BuyerRequestService._handle_request_expiration(request, FakeSession([offer]))

    assert offer.status is not None
    sellers = [c for c in captured if c["user_id"] == "USR_SELLER"]
    assert len(sellers) == 1


def test_a_failed_notification_still_expires_the_request(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("notifications down")

    monkeypatch.setattr(
        "app.notifications.services.NotificationService.create_notification", boom
    )
    request = FakeRequest()
    # With a pending offer, the seller notification is attempted first --
    # create_notification re-raises, so before the reordering this aborted
    # the whole sweep and left the request OPEN.
    BuyerRequestService._handle_request_expiration(request, FakeSession([FakeOffer()]))
    assert request.status is RequestStatus.EXPIRED
