"""Chasing an unclaimed order without paging riders every minute.

The sweep runs once a minute, so anything it does unconditionally it does
sixty times an hour. Escalation used to be one of those things: every order
unclaimed past ESCALATE_AFTER was re-pushed to every rider in range on every
sweep, for as long as it sat there. On the test server ten old orders did
that the moment beat started running, and riders got a push a minute each.

The rule now: one alert per widening, then hourly at the widest radius, then
nothing once a day has gone by.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

from app.deliveries import offers
from app.deliveries.models import DeliveryOrderAssignment
from app.orders.models import Order

PLACED = datetime(2026, 10, 6, 12, 0, 0)


class FakeRedis:
    def __init__(self, broken=False):
        self.store = {}
        self.broken = broken

    def set(self, name, value, ex=None, px=None, nx=False, xx=False):
        if self.broken:
            raise ConnectionError("redis is down")
        if nx and name in self.store:
            return None
        self.store[name] = value
        return True


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return list(self.rows)


def _session_for(orders):
    class Session:
        def query(self, model):
            if model is Order:
                return _Query(orders)
            if model is DeliveryOrderAssignment:
                return _Query([])
            raise AssertionError(f"unexpected query for {model}")

    return Session()


def _order(order_id="ORD_1", since=PLACED):
    class FakeOrder:
        pass

    o = FakeOrder()
    o.id = order_id
    o.updated_at = since
    o.created_at = since
    return o


def run_sweeps(minutes, orders=None, redis=None, start=PLACED):
    """Run the real sweep once a minute and return the alerts it sent, as
    (minute, order_id, radius)."""
    from contextlib import contextmanager

    orders = orders if orders is not None else [_order()]
    redis = redis or FakeRedis()
    session = _session_for(orders)
    sent = []
    clock = {"at": start}

    @contextmanager
    def scope():
        yield session

    def alert(order_id, radius_km=None, **_):
        minute = int((clock["at"] - start).total_seconds() // 60)
        sent.append((minute, order_id, radius_km))
        return 1

    with patch("app.libs.session.session_scope", scope), patch(
        "app.deliveries.rider_alerts.alert_nearby_riders", alert
    ), patch("external.redis.redis_client", redis), patch.object(
        offers, "now", lambda: clock["at"]
    ):
        for minute in range(minutes):
            clock["at"] = start + timedelta(minutes=minute)
            offers.sweep()
    return sent


class TestEscalationSlots:
    def test_a_young_order_has_no_slot(self):
        assert (
            offers.escalation_slot(offers.ESCALATE_AFTER - timedelta(seconds=1)) is None
        )

    def test_every_minute_of_one_widening_shares_a_slot(self):
        start = offers.ESCALATE_AFTER
        slots = {
            offers.escalation_slot(start + timedelta(minutes=m))
            for m in range(int(offers.ESCALATE_AFTER.total_seconds() // 60))
        }
        assert slots == {"step1"}

    def test_each_widening_is_its_own_slot(self):
        slots = [
            offers.escalation_slot(offers.ESCALATE_AFTER * n)
            for n in range(1, len(offers.ESCALATION_RADII_KM) + 1)
        ]
        assert len(set(slots)) == len(offers.ESCALATION_RADII_KM)

    def test_past_the_widest_radius_it_is_hourly(self):
        late = offers.ESCALATE_AFTER * (len(offers.ESCALATION_RADII_KM) + 1)
        assert offers.escalation_slot(late) == offers.escalation_slot(
            late + timedelta(minutes=5)
        )
        assert offers.escalation_slot(late) != offers.escalation_slot(
            late + offers.ESCALATION_REPEAT
        )

    def test_it_gives_up_after_a_day(self):
        assert offers.escalation_slot(offers.ESCALATION_GIVE_UP) is None
        assert offers.escalation_slot(timedelta(days=30)) is None


class TestTheSweepDoesNotPageEveryMinute:
    def test_the_first_hour_is_one_push_per_widening_not_sixty(self):
        sent = run_sweeps(60)
        # Minutes 10, 20, 30 widen; minute 40 is the first hourly repeat.
        assert [m for m, _, _ in sent] == [10, 20, 30, 40]
        assert [r for _, _, r in sent] == sorted(r for _, _, r in sent)

    def test_a_whole_day_unclaimed_is_a_handful_of_pushes(self):
        sent = run_sweeps(48 * 60)
        assert 0 < len(sent) <= 30  # was 24 * 60 - 10 = 1430
        give_up = int(offers.ESCALATION_GIVE_UP.total_seconds() // 60)
        assert all(m < give_up for m, _, _ in sent)

    def test_an_order_stuck_for_a_month_sends_nothing(self):
        # The test-server case: orders left READY_FOR_DELIVERY in September.
        sent = run_sweeps(30, orders=[_order(since=PLACED - timedelta(days=30))])
        assert sent == []

    def test_two_sweeps_in_the_same_minute_alert_once(self):
        redis = FakeRedis()
        start = PLACED + offers.ESCALATE_AFTER
        first = run_sweeps(1, redis=redis, start=start)
        second = run_sweeps(1, redis=redis, start=start)
        assert len(first) == 1 and second == []

    def test_each_order_is_chased_on_its_own(self):
        sent = run_sweeps(
            11,
            orders=[
                _order("ORD_A"),
                _order("ORD_B", since=PLACED + timedelta(minutes=1)),
            ],
        )
        assert [(m, o) for m, o, _ in sent] == [(10, "ORD_A")]

    def test_if_redis_is_down_it_skips_rather_than_floods(self):
        assert run_sweeps(60, redis=FakeRedis(broken=True)) == []
