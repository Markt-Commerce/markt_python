"""The buyer's delivery tracker, which never moved.

OrderDelivery.state is what the order detail screen draws its progress
list from -- Paid, Rider requested, Rider assigned, Picked up, On the
way, Delivered. Dispatch drove it as far as JOB_CREATED and then nothing
touched it again: no rider event anywhere in the codebase advanced it.

So a buyer watched "Rider requested / Waiting for someone to take it"
through the entire delivery and after the parcel was in their hands,
while the tracking screen beside it correctly read Delivered.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.delivery_pricing.order_delivery import DeliveryState as D
from app.delivery_pricing.order_delivery import OrderDelivery


def delivery(state: D) -> OrderDelivery:
    row = OrderDelivery(
        order_id="ORD_1",
        fee_minor=100_000,
        breakdown={},
        solo_fee_minor=100_000,
    )
    row.state = state
    return row


class TestWalkingForward:
    @pytest.mark.parametrize(
        "start,target,expected",
        [
            # The step each rider event reports.
            (D.JOB_CREATED, D.ASSIGNED, D.ASSIGNED),
            (D.ASSIGNED, D.PICKED_UP, D.PICKED_UP),
            (D.PICKED_UP, D.IN_TRANSIT, D.IN_TRANSIT),
            (D.IN_TRANSIT, D.DELIVERED, D.DELIVERED),
        ],
    )
    def test_each_step_lands(self, start, target, expected):
        row = delivery(start)
        assert row.advance_to(target) is True
        assert row.state is expected

    def test_it_passes_through_states_nothing_reports(self):
        # A rider confirms a pickup; no event anywhere says "assigned".
        # Every order accepted before rider events drove this state at
        # all is sitting at JOB_CREATED, so this is the normal case and
        # not an edge one -- a single transition_to would raise here.
        row = delivery(D.JOB_CREATED)
        assert row.advance_to(D.PICKED_UP) is True
        assert row.state is D.PICKED_UP

    def test_a_whole_delivery_in_one_move(self):
        row = delivery(D.PAID)
        assert row.advance_to(D.DELIVERED) is True
        assert row.state is D.DELIVERED

    def test_a_parked_delivery_rejoins_the_path(self):
        # AWAITING_DISPATCH is paid-but-undispatched. A rider accepting it
        # is exactly the thing that unparks it.
        row = delivery(D.AWAITING_DISPATCH)
        assert row.advance_to(D.ASSIGNED) is True
        assert row.state is D.ASSIGNED


class TestItNeverGoesBackwards:
    def test_a_late_duplicate_does_not_rewind(self):
        # Status updates can arrive out of order on a bad connection.
        row = delivery(D.IN_TRANSIT)
        assert row.advance_to(D.PICKED_UP) is False
        assert row.state is D.IN_TRANSIT

    def test_a_delivered_parcel_stays_delivered(self):
        row = delivery(D.DELIVERED)
        assert row.advance_to(D.IN_TRANSIT) is False
        assert row.state is D.DELIVERED

    def test_standing_still_is_not_a_change(self):
        row = delivery(D.ASSIGNED)
        assert row.advance_to(D.ASSIGNED) is False
        assert row.state is D.ASSIGNED


class TestEndings:
    def test_a_failed_attempt_is_recorded(self):
        # The one state change a buyer most needs to see, and the failure
        # path did not set it either.
        row = delivery(D.IN_TRANSIT)
        assert row.advance_to(D.FAILED) is True
        assert row.state is D.FAILED

    def test_failure_is_reachable_from_the_moment_a_rider_has_it(self):
        for state in (D.ASSIGNED, D.PICKED_UP, D.IN_TRANSIT):
            row = delivery(state)
            assert row.advance_to(D.FAILED) is True, state

    def test_a_delivered_parcel_cannot_then_fail(self):
        row = delivery(D.DELIVERED)
        assert row.advance_to(D.FAILED) is False
        assert row.state is D.DELIVERED

    def test_a_failed_delivery_is_not_quietly_resurrected(self):
        # Retrying is a deliberate reassignment, not something a stray
        # status update from an old screen should do.
        row = delivery(D.FAILED)
        assert row.advance_to(D.IN_TRANSIT) is False
        assert row.state is D.FAILED


class TestTheRiderMappingIsHonest:
    def test_at_the_shop_is_not_picked_up(self):
        from app.deliveries.models import LogisticalStatus
        from app.deliveries.services import DeliveryService

        mapping = DeliveryService._BUYER_DELIVERY_STATE
        # A rider standing in the shop has not collected anything, and a
        # parcel at the door with the code unconfirmed is not delivered.
        assert LogisticalStatus.ARRIVED_PICKUP not in mapping
        assert LogisticalStatus.DELIVERED_PENDING_QR not in mapping

    def test_the_steps_that_do_move_it(self):
        from app.deliveries.models import LogisticalStatus
        from app.deliveries.services import DeliveryService

        mapping = DeliveryService._BUYER_DELIVERY_STATE
        assert mapping[LogisticalStatus.PICKED_UP] is D.PICKED_UP
        assert mapping[LogisticalStatus.EN_ROUTE_TO_DROPOFF] is D.IN_TRANSIT
        assert mapping[LogisticalStatus.COMPLETED] is D.DELIVERED


class TestASpentCodeIsNotACode:
    """The buyer's POD code, after the rider has already used it.

    get_buyer_pod_code returned the escrow code for as long as the
    assignment row existed, which is forever. So once the rider had
    scanned it and ridden off, the app still offered "View my delivery
    code" and still drew a live QR for a delivery that was over.
    """

    def test_a_completed_single_order_reports_delivered(self, monkeypatch):
        from app.deliveries.models import AssignmentStatus, LogisticalStatus

        out = _pod_code(
            monkeypatch,
            assignment=SimpleNamespace(
                escrow_qr_code="abc",
                logistical_status=LogisticalStatus.COMPLETED,
                status=AssignmentStatus.ACCEPTED,
            ),
        )
        assert out["delivered"] is True
        assert out["ready"] is False
        assert out["code"] is None

    def test_a_live_delivery_still_hands_over_the_code(self, monkeypatch):
        from app.deliveries.models import AssignmentStatus, LogisticalStatus

        out = _pod_code(
            monkeypatch,
            assignment=SimpleNamespace(
                escrow_qr_code="abc",
                logistical_status=LogisticalStatus.EN_ROUTE_TO_DROPOFF,
                status=AssignmentStatus.ACCEPTED,
            ),
        )
        assert out["ready"] is True
        assert out["code"] == "abc"
        assert out["delivered"] is False

    def test_waiting_for_a_rider_is_not_delivered(self, monkeypatch):
        # Nothing to show yet, but the order is not finished either --
        # the two must not look the same to the app.
        out = _pod_code(monkeypatch, assignment=None)
        assert out["ready"] is False
        assert out["delivered"] is False


def _pod_code(monkeypatch, assignment):
    """Drive get_buyer_pod_code with a stubbed session."""
    from app.deliveries.services import DeliveryService

    order = SimpleNamespace(buyer=SimpleNamespace(user_id="USR_1"))

    session = MagicMock()

    def query(model):
        q = MagicMock()
        name = getattr(model, "__name__", str(model))
        if name == "Order":
            q.options.return_value.get.return_value = order
        elif name == "DeliveryOrderAssignment":
            chain = q.filter_by.return_value.order_by.return_value
            chain.first.return_value = assignment
        else:  # DeliveryRunOrder
            q.filter_by.return_value.first.return_value = None
        return q

    session.query.side_effect = query

    scope = MagicMock()
    scope.return_value.__enter__.return_value = session
    monkeypatch.setattr("app.deliveries.services.session_scope", scope)

    return DeliveryService.get_buyer_pod_code("ORD_1", "USR_1")
