"""Real-database concurrency test for InventoryService.reserve_stock (8.2).

Every other test in this suite mocks the DB session, which can prove the
code *calls* with_for_update() but can't prove the lock actually serializes
concurrent requests. This test runs two real reservation attempts against a
real Postgres row from separate threads/connections to prove that.

This test creates and drops tables (db.create_all()/db.drop_all()), so it
must only ever run against a disposable database -- it is gated behind
RUN_DB_TESTS=1, set explicitly in ci.yml for the job that provisions a
throwaway Postgres service container. It is SKIPPED by default (including
a bare local `pytest tests/`) specifically so it can never point at
whatever DB_* a developer's environment happens to be configured with,
e.g. via settings.ini -- running it once locally without this gate is
exactly what led to it being added.
"""

import os
import threading

import pytest
from flask import Flask

from app.libs.errors import ConflictError
from app.inventory.services import InventoryService
from app.products.models import Product
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


def _attempt_reserve(app, product_id, buyer_id, quantity, results, index):
    with app.app_context():
        try:
            reservation = InventoryService.reserve_stock(
                product_id, buyer_id=buyer_id, quantity=quantity
            )
            results[index] = ("ok", reservation.id)
        except ConflictError as exc:
            results[index] = ("conflict", str(exc))
        except Exception as exc:  # surfaced in the assertion message, not swallowed
            results[index] = ("error", repr(exc))


def test_two_concurrent_reservations_against_stock_one_only_one_succeeds(db_app):
    with db_app.app_context():
        product = Product(name="Concurrency Test Product", price=1000.0, stock=1)
        buyer_a = Buyer()
        buyer_b = Buyer()
        db.session.add_all([product, buyer_a, buyer_b])
        db.session.commit()
        product_id, buyer_a_id, buyer_b_id = product.id, buyer_a.id, buyer_b.id

    results = [None, None]
    threads = [
        threading.Thread(
            target=_attempt_reserve,
            args=(db_app, product_id, buyer_a_id, 1, results, 0),
        ),
        threading.Thread(
            target=_attempt_reserve,
            args=(db_app, product_id, buyer_b_id, 1, results, 1),
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    outcomes = [r[0] if r else "timed_out" for r in results]
    assert outcomes.count("ok") == 1, f"expected exactly one success, got {results}"
    assert (
        outcomes.count("conflict") == 1
    ), f"expected exactly one conflict, got {results}"

    with db_app.app_context():
        available = InventoryService.get_available_quantity(product_id)
        assert available == 0
