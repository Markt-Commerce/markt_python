"""Seller matching runs against a real database, because the bug was in SQL.

Creating a buyer request notifies sellers who stock its primary category.
That query joined sellers to products to categories, which is one-to-many by
nature, and deduped the result with DISTINCT over the whole Seller row.

Postgres cannot do that. `Seller.policies` is a plain `json` column, and
`json` has no equality operator -- only `jsonb` does -- so the query died
with "could not identify an equality operator for type json" and every
buyer request naming a category that some active seller stocked came back a
500. Requests with no categories, or with categories nobody sells in, never
reached the query, which is what made it look intermittent.

No amount of mocking catches this: a MagicMock session answers DISTINCT
happily. It needs a database with the real column types.

Gated on RUN_DB_TESTS=1 like the other real-database tests.
"""

import os
import uuid

import pytest

from app.categories.models import Category, ProductCategory
from app.products.models import Product
from app.requests.services import BuyerRequestService
from app.users.models import Buyer, Seller, User
from external.database import db
from main.setup import create_flask_app

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason=(
        "requires a disposable database; set RUN_DB_TESTS=1 only when DB_* "
        "points at a throwaway Postgres instance"
    ),
)


@pytest.fixture(scope="module")
def app():
    flask_app = create_flask_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def world(app):
    """One category, one seller with two products in it, one buyer.

    Two products on purpose: that is what makes the join return the same
    seller twice, which is what the DISTINCT is there to collapse.
    """
    with app.app_context():
        tag = uuid.uuid4().hex[:8]

        category = Category(name=f"cat-{tag}", description="test")
        db.session.add(category)

        seller_user = User(
            email=f"s.{tag}@markt-test.example.com",
            username=f"s{tag}",
            email_verified=True,
        )
        buyer_user = User(
            email=f"b.{tag}@markt-test.example.com",
            username=f"b{tag}",
            email_verified=True,
        )
        db.session.add_all([seller_user, buyer_user])
        db.session.flush()

        seller = Seller(
            user_id=seller_user.id,
            shop_name=f"Shop {tag}",
            description="test shop",
            is_active=True,
            # The column at the heart of it. A row with a json value present
            # is what Postgres refuses to compare.
            policies={"returns": "14 days", "shipping": "next day"},
        )
        buyer = Buyer(user_id=buyer_user.id, buyername=f"Buyer {tag}")
        db.session.add_all([seller, buyer])
        db.session.flush()

        products = []
        for i in range(2):
            product = Product(
                seller_id=seller.id,
                name=f"product-{tag}-{i}",
                description="test",
                price=1000,
                status=Product.Status.ACTIVE,
            )
            db.session.add(product)
            db.session.flush()
            db.session.add(
                ProductCategory(product_id=product.id, category_id=category.id)
            )
            products.append(product)

        db.session.commit()

        yield {
            "category": category,
            "seller": seller,
            "seller_user": seller_user,
            "buyer": buyer,
        }

        for product in products:
            db.session.query(ProductCategory).filter_by(product_id=product.id).delete()
            db.session.delete(product)
        db.session.delete(seller)
        db.session.delete(buyer)
        db.session.delete(category)
        db.session.delete(seller_user)
        db.session.delete(buyer_user)
        db.session.commit()


class FakeRequest:
    """Just the fields _notify_relevant_sellers reads."""

    def __init__(self, category_id):
        self.id = "REQ_TEST"
        self.title = "Need an adapter"
        self.market_id = None
        self.categories = [
            type("RC", (), {"is_primary": True, "category_id": category_id})()
        ]


class TestMatchingSellersDoesNotBlowUp:
    def test_a_request_in_a_stocked_category_notifies_the_seller(
        self, app, world, monkeypatch
    ):
        sent = []
        monkeypatch.setattr(
            "app.notifications.services.NotificationService.create_notification",
            lambda **kw: sent.append(kw),
        )

        with app.app_context():
            # This raised ProgrammingError before: DISTINCT over a Seller row
            # carrying a json column.
            BuyerRequestService._notify_relevant_sellers(
                FakeRequest(world["category"].id)
            )

        assert [s["user_id"] for s in sent] == [world["seller_user"].id]

    def test_the_seller_is_notified_once_despite_two_matching_products(
        self, app, world, monkeypatch
    ):
        # The reason DISTINCT is in the query at all. Two products in the
        # category means the join yields the seller twice; notifying them
        # twice for one request would be spam.
        sent = []
        monkeypatch.setattr(
            "app.notifications.services.NotificationService.create_notification",
            lambda **kw: sent.append(kw),
        )

        with app.app_context():
            BuyerRequestService._notify_relevant_sellers(
                FakeRequest(world["category"].id)
            )

        assert len(sent) == 1

    def test_a_category_nobody_stocks_notifies_nobody(self, app, world, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "app.notifications.services.NotificationService.create_notification",
            lambda **kw: sent.append(kw),
        )

        with app.app_context():
            BuyerRequestService._notify_relevant_sellers(FakeRequest(-1))

        assert sent == []
