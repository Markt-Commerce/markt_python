"""Real-database concurrency test for DeliveryRunService.get_or_create_open_run's
package-count capacity guard (10.4, Phase 11's "load-test capacity
constraint under concurrent order joins").

Every other delivery-run test in this suite mocks the DB session, which
can prove the code *calls* with_for_update() but can't prove the lock
actually serializes concurrent order-joins the way it's meant to. This
test drives two real attach attempts against a real Postgres row (a run
with max_packages=1) from separate threads/connections to prove a
concurrent second attacher can't push it over capacity -- it must get
routed to a fresh run instead.

Same disposable-database discipline as test_inventory_concurrency.py:
gated behind RUN_DB_TESTS=1, creates/drops tables, must never run against
a real dev database.
"""

import os
import threading

import pytest
from flask import Flask

from app.deliveries.models import DeliveryRun, DeliveryRunOrder, DeliveryRunStatus
from app.deliveries.runs import DeliveryRunService
from app.libs.session import session_scope
from app.markets.models import Area, Market
from app.orders.models import Order
from app.users.models import Buyer
from external.database import database, db

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason=(
        "requires a disposable database; set RUN_DB_TESTS=1 only when "
        "DB_* points at a throwaway Postgres instance (this test runs "
        "create_all()/drop_all())"
    ),
)


@pytest.fixture(scope="module")
def db_app():
    app = Flask(__name__)
    database.init_app(app)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _attempt_join(app, market_id, area_id, order_id, results, index):
    with app.app_context():
        try:
            with session_scope() as session:
                run = DeliveryRunService.get_or_create_open_run(
                    session, market_id, area_id
                )
                run_id = run.id
                session.add(DeliveryRunOrder(delivery_run_id=run_id, order_id=order_id))
            results[index] = ("ok", run_id)
        except Exception as exc:  # surfaced in the assertion, not swallowed
            results[index] = ("error", repr(exc))


def test_two_concurrent_joins_against_a_one_package_run_dont_overfill_it(db_app):
    with db_app.app_context():
        market = Market(name="Concurrency Test Market", slug="concurrency-market")
        area = Area(name="Concurrency Test Area", slug="concurrency-area")
        buyer_a = Buyer()
        buyer_b = Buyer()
        db.session.add_all([market, area, buyer_a, buyer_b])
        db.session.flush()

        run = DeliveryRun(
            market_id=market.id,
            area_id=area.id,
            status=DeliveryRunStatus.OPEN,
            max_packages=1,
            max_weight_grams=50_000,
            cutoff_at=db.func.now(),
        )
        order_a = Order(buyer_id=buyer_a.id)
        order_b = Order(buyer_id=buyer_b.id)
        db.session.add_all([run, order_a, order_b])
        db.session.commit()
        market_id, area_id = market.id, area.id
        order_a_id, order_b_id = order_a.id, order_b.id
        original_run_id = run.id

    results = [None, None]
    threads = [
        threading.Thread(
            target=_attempt_join,
            args=(db_app, market_id, area_id, order_a_id, results, 0),
        ),
        threading.Thread(
            target=_attempt_join,
            args=(db_app, market_id, area_id, order_b_id, results, 1),
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    outcomes = [r[0] if r else "timed_out" for r in results]
    assert outcomes == ["ok", "ok"], f"expected both to succeed, got {results}"

    run_ids_used = {r[1] for r in results}
    # The capacity guard must have routed the second attacher to a fresh
    # run rather than letting it join the same, now-full one.
    assert len(run_ids_used) == 2, f"expected two distinct runs, got {results}"
    assert original_run_id in run_ids_used

    with db_app.app_context():
        for run_id in run_ids_used:
            package_count = (
                db.session.query(DeliveryRunOrder)
                .filter_by(delivery_run_id=run_id)
                .count()
            )
            assert package_count == 1, (
                f"run {run_id} should hold exactly 1 package, has " f"{package_count}"
            )
