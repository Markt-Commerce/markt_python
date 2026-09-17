"""The emails a buyer and seller get as an order moves.

Before this, a buyer who paid heard nothing until the thing arrived: no
notification was ever created with type ORDER_PLACED or ORDER_UPDATE, so the
templates, channels and email wiring for both existed and never ran. These
tests are mostly about the emission, because that is the half that fails
without an error.
"""

import re

import pytest

from app.libs import email_layout as L
from app.libs.email_service import EmailService
from app.notifications.models import NotificationType
from app.orders.models import OrderStatus
from app.orders.services import OrderService
from app.payments.services import PaymentService


def txt(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


@pytest.fixture
def svc():
    return EmailService.__new__(EmailService)


@pytest.fixture
def captured(monkeypatch):
    """Record notifications instead of creating them."""
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(
        "app.notifications.services.NotificationService.create_notification", fake
    )
    return calls


class TestStatusChangeIsAnnounced:
    @pytest.mark.parametrize(
        "status",
        [OrderStatus.READY_FOR_DELIVERY, OrderStatus.SHIPPED, OrderStatus.DELIVERED],
    )
    def test_buyer_hears_about_the_stages_in_between(self, captured, status):
        OrderService._notify_status_change("ORD_1", "USR_1", "MK-1", status)
        assert len(captured) == 1
        assert captured[0]["notification_type"] is NotificationType.ORDER_UPDATE
        assert captured[0]["user_id"] == "USR_1"
        assert captured[0]["metadata_"]["status"] == status.value
        # The order *number*, not the internal id: it is what a buyer can
        # quote to support.
        assert captured[0]["metadata_"]["order_number"] == "MK-1"

    @pytest.mark.parametrize(
        "status",
        [OrderStatus.CANCELLED, OrderStatus.RETURNED, OrderStatus.FAILED],
    )
    def test_terminal_statuses_are_left_to_their_own_notifications(
        self, captured, status
    ):
        # ORDER_CANCELLED and REFUND_ISSUED are emitted by the paths that know
        # why. Two emails about one cancellation is worse than one.
        OrderService._notify_status_change("ORD_1", "USR_1", "MK-1", status)
        assert captured == []

    def test_nothing_is_sent_to_nobody(self, captured):
        OrderService._notify_status_change("ORD_1", None, "MK-1", OrderStatus.SHIPPED)
        assert captured == []

    def test_a_failure_to_notify_does_not_break_the_order(self, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("notification service down")

        monkeypatch.setattr(
            "app.notifications.services.NotificationService.create_notification", boom
        )
        OrderService._notify_status_change(
            "ORD_1", "USR_1", "MK-1", OrderStatus.SHIPPED
        )


class TestEmailData:
    def test_order_number_comes_from_metadata_not_the_reference_id(self):
        from app.notifications.tasks import _order_email_data

        data = _order_email_data(
            {"reference_id": "ORD_abc123"},
            {"order_number": "MK-24081", "status": "shipped"},
        )
        # The old code put the ORD_ id in front of the buyer as their order
        # number.
        assert data["order_number"] == "MK-24081"
        assert data["status"] == "shipped"

    def test_a_non_order_reference_is_not_looked_up(self):
        from app.notifications.tasks import _order_email_data

        data = _order_email_data({"reference_id": "PAY_x"}, {"amount": 500})
        assert data["amount"] == 500
        assert data["items"] == []


class TestFailureReason:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ({"gateway_response": "Insufficient funds"}, "Insufficient funds"),
            ({"message": "Declined by bank"}, "Declined by bank"),
            ({"data": {"gateway_response": "Card expired"}}, "Card expired"),
            ("Timed out", "Timed out"),
            ({}, ""),
            (None, ""),
            ({"gateway_response": "   "}, ""),
        ],
    )
    def test_reads_the_gateways_own_words(self, raw, expected):
        payment = type("P", (), {"gateway_response": raw})()
        assert PaymentService._failure_reason(payment) == expected


class TestProgressTracker:
    def test_marks_the_current_step(self):
        html = L.progress(["A", "B", "C"], 1)
        assert "A" in html and "B" in html and "C" in html

    def test_the_bar_fills_as_the_order_moves(self):
        # Each step reached paints one more dot (and its connector) in the
        # brand colour, so a later step is strictly more filled in.
        filled = [L.progress(["A", "B", "C", "D"], i).count(L.BRAND) for i in range(4)]
        assert filled == sorted(filled)
        assert filled[0] < filled[-1]

    def test_steps_not_yet_reached_stay_grey(self):
        assert L.HAIRLINE in L.progress(["A", "B", "C"], 0)
        # Everything done: nothing left grey.
        assert L.HAIRLINE not in L.progress(["A", "B", "C"], 2)

    def test_an_unknown_step_index_is_clamped_not_raised(self):
        assert L.progress(["A", "B"], 99)
        assert L.progress(["A", "B"], -3)

    def test_no_steps_renders_nothing(self):
        assert L.progress([], 0) == ""

    def test_tracker_is_tables_only(self):
        html = L.progress(["A", "B", "C"], 1)
        assert "display:flex" not in html.replace(" ", "")
        assert "display:grid" not in html.replace(" ", "")


class TestStatusEmail:
    def test_speaks_to_the_buyer_not_the_database(self, svc):
        body = txt(
            svc._get_order_status_update_template(
                {"order_number": "MK-1", "status": "ready_for_delivery"}
            )
        )
        # Not "is now Ready For Delivery".
        assert "Your order is packed" in body
        assert "Ready For Delivery" not in body

    def test_a_cancelled_order_gets_no_progress_tracker(self, svc):
        body = txt(
            svc._get_order_status_update_template(
                {"order_number": "MK-1", "status": "cancelled"}
            )
        )
        assert "On the way" not in body
        assert "was cancelled" in body

    def test_an_unknown_status_still_sends(self, svc):
        body = txt(
            svc._get_order_status_update_template(
                {"order_number": "MK-1", "status": "quantum_superposition"}
            )
        )
        assert "quantum superposition" in body

    def test_rider_and_eta_appear_only_when_known(self, svc):
        with_rider = txt(
            svc._get_order_status_update_template(
                {
                    "order_number": "MK-1",
                    "status": "shipped",
                    "rider_name": "Musa A.",
                    "eta": "Today, 4-6pm",
                }
            )
        )
        assert "Musa A." in with_rider and "Today, 4-6pm" in with_rider

        without = txt(
            svc._get_order_status_update_template(
                {"order_number": "MK-1", "status": "shipped"}
            )
        )
        assert "Your rider" not in without
        assert "Expected" not in without


class TestConfirmationEmail:
    def test_lists_what_was_bought(self, svc):
        body = txt(
            svc._get_order_confirmation_template(
                {
                    "order_number": "MK-1",
                    "total": 31000.0,
                    "buyer_name": "Tunde",
                    "delivery_address": "12 Awolowo Rd",
                    "items": [
                        {
                            "product_name": "Ankara Tote",
                            "quantity": 2,
                            "price": 7500.0,
                        }
                    ],
                }
            )
        )
        assert "Ankara Tote" in body
        assert "₦31,000.00" in body
        assert "12 Awolowo Rd" in body
        assert "Tunde" in body

    def test_survives_an_order_with_no_items(self, svc):
        body = txt(svc._get_order_confirmation_template({"order_number": "MK-1"}))
        assert "MK-1" in body


class TestSellerEmail:
    def test_tells_the_seller_what_to_pack(self, svc):
        body = txt(
            svc._get_seller_order_notification_template(
                {
                    "order_number": "MK-1",
                    "total": 15000.0,
                    "buyer_name": "Tunde",
                    "items": [
                        {"product_name": "Jersey", "quantity": 1, "price": 15000.0}
                    ],
                }
            )
        )
        assert "What to pack" in body
        assert "Jersey" in body
        # Not the buyer's receipt copy, which is what sellers used to get.
        assert "keep this email as your receipt" not in body.lower()
