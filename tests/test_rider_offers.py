"""Holding an order for a rider, without losing the order.

The countdown in the app is only meaningful if the order is genuinely held
while it runs. But every hold is a chance to strand an order, so these are
mostly about the ways an order could go missing and the rules that stop it.

The one failure this whole design exists to prevent: an order nobody is
carrying that nobody can see.
"""

from datetime import datetime, timedelta

import pytest

from app.deliveries import offers
from app.deliveries.models import AssignmentStatus


NOW = datetime(2026, 9, 19, 12, 0, 0)


def row(status, expires_at=None, rider="DEL_1"):
    class Row:
        pass

    r = Row()
    r.status = status
    r.expires_at = expires_at
    r.delivery_user_id = rider
    r.assignment_id = "ASG_1"
    return r


class TestALiveHold:
    def test_a_hold_that_has_not_run_out_is_live(self):
        assert offers.is_live_offer(
            row(AssignmentStatus.OFFERED, NOW + timedelta(seconds=10)), NOW
        )

    def test_a_hold_past_its_expiry_is_not_live(self):
        # The sweep runs on a schedule. An order's availability cannot wait
        # on a scheduler, so an expired row stops holding the moment it
        # expires, not the moment something notices.
        assert not offers.is_live_offer(
            row(AssignmentStatus.OFFERED, NOW - timedelta(seconds=1)), NOW
        )

    def test_a_hold_with_no_expiry_is_treated_as_over(self):
        # A hold that never ends is the exact thing this module exists to
        # prevent, so an unbounded one fails open rather than forever.
        assert not offers.is_live_offer(row(AssignmentStatus.OFFERED, None), NOW)

    def test_exactly_at_the_expiry_it_is_over(self):
        assert not offers.is_live_offer(row(AssignmentStatus.OFFERED, NOW), NOW)


class TestNothingHidesAnOrderForever:
    def test_an_old_decline_stops_hiding_it(self):
        past = row(AssignmentStatus.REJECTED, NOW - timedelta(seconds=1))
        assert not offers.suppresses_for_rider(past, NOW)

    def test_a_fresh_decline_hides_it_for_now(self):
        fresh = row(AssignmentStatus.REJECTED, NOW + timedelta(minutes=5))
        assert offers.suppresses_for_rider(fresh, NOW)

    def test_a_decline_with_no_expiry_does_not_hide_it(self):
        # Rows written before declines were time-boxed have no expiry. They
        # must not keep hiding the order, or the old permanent-decline bug
        # survives in the data.
        legacy = row(AssignmentStatus.REJECTED, None)
        assert not offers.suppresses_for_rider(legacy, NOW)

    def test_a_lapsed_offer_comes_back_sooner_than_a_decline(self):
        # Missing a countdown is not a decision about the order.
        assert offers.LAPSE_COOLDOWN < offers.DECLINE_COOLDOWN

    def test_a_failed_assignment_does_not_hide_it(self):
        assert not offers.suppresses_for_rider(row(AssignmentStatus.FAILED), NOW)

    def test_an_accepted_assignment_is_not_a_suppression(self):
        # It is handled as "taken", which is a different thing: taken hides
        # the order from everyone, not just from one rider.
        assert not offers.suppresses_for_rider(row(AssignmentStatus.ACCEPTED), NOW)


class TestEscalation:
    def test_a_young_order_is_not_escalated(self):
        assert offers.escalation_radius_km(timedelta(minutes=1)) is None

    def test_an_order_nobody_took_widens_the_search(self):
        first = offers.escalation_radius_km(offers.ESCALATE_AFTER)
        assert first is not None
        assert first >= offers.ESCALATION_RADII_KM[0]

    def test_it_keeps_widening(self):
        radii = [
            offers.escalation_radius_km(offers.ESCALATE_AFTER * n) for n in range(1, 5)
        ]
        assert radii == sorted(radii)

    def test_it_stops_widening_somewhere(self):
        # Past a point the ride to the pickup costs more than the delivery
        # pays, and a rider who accepts is worse off for having done it.
        very_late = offers.escalation_radius_km(offers.ESCALATE_AFTER * 100)
        assert very_late == max(offers.ESCALATION_RADII_KM)

    def test_the_first_escalation_is_wider_than_the_original_alert(self):
        from app.deliveries.rider_alerts import ALERT_RADIUS_KM

        assert max(offers.ESCALATION_RADII_KM) > ALERT_RADIUS_KM


class TestTheClockIsTheServers:
    def test_an_offer_expires_a_fixed_time_from_now(self):
        assert offers.offer_expiry(NOW) == NOW + timedelta(seconds=offers.OFFER_SECONDS)

    def test_the_countdown_is_long_enough_to_read_and_short_enough_to_matter(self):
        assert 10 <= offers.OFFER_SECONDS <= 60


class TestAlertsCanWiden:
    def test_alert_nearby_riders_accepts_a_radius(self):
        import inspect

        from app.deliveries.rider_alerts import alert_nearby_riders

        assert "radius_km" in inspect.signature(alert_nearby_riders).parameters


class TestTheSweepIsScheduled:
    def test_it_runs_often_enough_to_release_a_thirty_second_hold(self):
        # A hold released by a sweep that runs hourly is a hold that lasts an
        # hour, whatever the countdown said.
        from main.schedules import CELERYBEAT_SCHEDULE

        entry = CELERYBEAT_SCHEDULE["sweep-delivery-offers"]
        assert entry["task"] == "app.deliveries.tasks.sweep_delivery_offers"
        assert entry["schedule"].minute == set(range(60))
