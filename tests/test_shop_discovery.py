"""Shop discovery: proximity ranking, category filtering, and the query contract.

Against a real database with real Nigerian coordinates, because the things
worth proving here are arithmetic and SQL:

  * a bounding box is a *superset* of a circle, so the Haversine second pass
    is not optional -- a test with mocked rows cannot tell the two apart
  * ordering by distance cannot be expressed in the query, so pagination has
    to rank the whole radius before slicing; only a multi-page assertion
    catches the version that sorts each page separately
  * the category filter referenced a column that does not exist, which the
    service's broad `except` turned into a 500

Gated on RUN_DB_TESTS=1 like the other real-database tests.
"""

import os
import uuid

import pytest

from app.categories.models import Category, SellerCategory
from app.users.models import Seller, User
from app.users.services import ShopService
from external.database import db
from main.setup import create_flask_app

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason=(
        "requires a disposable database; set RUN_DB_TESTS=1 only when DB_* "
        "points at a throwaway Postgres instance"
    ),
)

# Real places, so the distances below are checkable against a map.
IKEJA = (6.6018, 3.3515)  # the shopper
OGBA = (6.6250, 3.3400)  # ~2.9 km  -- inside the first rung
NEAR_5KM = (6.6518, 3.3515)  # ~5.6 km -- also inside the first rung
NEAR_8KM = (6.6718, 3.3515)  # ~7.8 km -- also inside the first rung
LEKKI = (6.4698, 3.5852)  # ~29.7 km -- needs the second rung
IBADAN = (7.3775, 3.9470)  # ~108 km  -- needs the third
ABUJA = (9.0765, 7.3986)  # ~520 km  -- past every rung


@pytest.fixture(scope="module")
def app():
    flask_app = create_flask_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def shops(app):
    """Creates sellers on demand and removes them afterwards.

    The marker below is what keeps these tests from reading each other's rows
    (and any real data): every assertion filters the result down to the shops
    this test made.
    """
    marker = uuid.uuid4().hex[:8]
    made = []

    def make(name, coords=None, *, categories=(), banner=None, active=True):
        with app.app_context():
            user = User(
                email=f"{marker}-{len(made)}@markt.test",
                username=f"u{marker}{len(made)}",
                is_seller=True,
            )
            user.set_password("Passw0rdy")
            db.session.add(user)
            db.session.flush()

            seller = Seller(
                user_id=user.id,
                shop_name=f"{name} {marker}",
                description=f"{name} sells things.",
                is_active=active,
                banner_url=banner,
                shop_latitude=coords[0] if coords else None,
                shop_longitude=coords[1] if coords else None,
            )
            db.session.add(seller)
            db.session.flush()

            for cat_id in categories:
                db.session.add(SellerCategory(seller_id=seller.id, category_id=cat_id))

            db.session.commit()
            made.append((user.id, seller.id))
            return seller.id

    make.marker = marker
    yield make

    with app.app_context():
        for user_id, seller_id in made:
            db.session.query(SellerCategory).filter_by(seller_id=seller_id).delete()
            db.session.query(Seller).filter_by(id=seller_id).delete()
            db.session.query(User).filter_by(id=user_id).delete()
        db.session.commit()


@pytest.fixture
def category(app):
    """A category to filter on, removed afterwards."""
    slug = f"testcat-{uuid.uuid4().hex[:8]}"
    with app.app_context():
        cat = Category(name=slug, slug=slug)
        db.session.add(cat)
        db.session.commit()
        cat_id = cat.id
    yield SimpleCategory(cat_id, slug)
    with app.app_context():
        # The junction rows have to go first, and they cannot be left to the
        # `shops` fixture: pytest tears fixtures down in reverse creation
        # order, which drops the category while sellers still reference it.
        db.session.query(SellerCategory).filter_by(category_id=cat_id).delete()
        db.session.query(Category).filter_by(id=cat_id).delete()
        db.session.commit()


class SimpleCategory:
    def __init__(self, id, slug):
        self.id, self.slug = id, slug


def _search(app, shops, **args):
    """Run a search scoped to the shops this test created.

    Scoped in the *query*, via the marker in each shop name, not by filtering
    the result afterwards. Filtering afterwards was not isolation: the radius
    ladder still saw every other shop in the database, so a rung could fill up
    with rows belonging to nobody and stop widening — which made these tests
    pass against an empty database and fail against a populated one. That is
    the worst possible way round.
    """
    args.setdefault("per_page", 50)
    args.setdefault("search", shops.marker)
    with app.app_context():
        return ShopService.search_shops(args)


def _names(result):
    return [s["shop_name"].split(" ")[0] for s in result["shops"]]


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------


def test_a_shop_down_the_road_answers_on_the_first_rung(app, shops):
    shops("Ogba", OGBA)
    result = _search(
        app,
        shops,
        latitude=IKEJA[0],
        longitude=IKEJA[1],
        sort_by="nearby",
        per_page=1,
    )

    assert result["location"]["applied"] is True
    assert result["location"]["radius_km"] == 10.0
    assert _names(result) == ["Ogba"]
    assert result["shops"][0]["distance_km"] == pytest.approx(2.9, abs=0.3)


def test_the_radius_widens_rather_than_returning_nothing(app, shops):
    """Lekki is 30 km away: outside the first rung, inside the second. An
    empty screen is the outcome the ladder exists to prevent."""
    shops("Lekki", LEKKI)
    result = _search(
        app,
        shops,
        latitude=IKEJA[0],
        longitude=IKEJA[1],
        sort_by="nearby",
        per_page=1,
    )

    assert result["location"]["radius_km"] == 50.0
    assert result["shops"][0]["distance_km"] == pytest.approx(29.7, abs=1.0)


def test_a_shop_past_every_rung_still_appears(app, shops):
    """Abuja is ~520 km from Lagos -- past 200 km, the widest rung.

    The list stops being distance-restricted, and says so, rather than
    rendering nothing.
    """
    shops("Abuja", ABUJA)
    result = _search(
        app, shops, latitude=IKEJA[0], longitude=IKEJA[1], sort_by="nearby"
    )

    assert result["location"]["applied"] is False
    assert result["location"]["radius_km"] is None
    assert _names(result) == ["Abuja"]


def test_the_box_alone_would_not_be_enough(app, shops):
    """A 10 km bounding box around Ikeja reaches ~14.1 km at its corners.

    `Corner` sits in that corner: inside the box, outside the circle. Without
    the Haversine pass the 10 km rung accepts it, has enough to fill the page,
    and stops -- so `Farther`, a genuine 40 km neighbour that the 50 km rung
    would have found, never appears at all. Skipping the second pass does not
    just mislabel a distance; it truncates the list.
    """
    corner = (IKEJA[0] + 0.089, IKEJA[1] + 0.089)  # ~13.9 km
    farther = (IKEJA[0] + 0.36, IKEJA[1])  # ~39.8 km
    shops("Corner", corner)
    shops("Farther", farther)

    result = _search(
        app,
        shops,
        latitude=IKEJA[0],
        longitude=IKEJA[1],
        sort_by="nearby",
        per_page=1,
        page=2,
    )

    assert _names(result) == [
        "Farther"
    ], "the 10 km rung must reject a shop 13.9 km away and keep widening"
    assert result["shops"][0]["distance_km"] == pytest.approx(39.8, abs=1.0)


# ---------------------------------------------------------------------------
# Ordering, including across pages
# ---------------------------------------------------------------------------


def test_nearest_first(app, shops):
    shops("Ibadan", IBADAN)
    shops("Ogba", OGBA)
    shops("Lekki", LEKKI)

    result = _search(
        app, shops, latitude=IKEJA[0], longitude=IKEJA[1], sort_by="nearby"
    )
    assert _names(result) == ["Ogba", "Lekki", "Ibadan"]


def test_pages_stay_in_distance_order_across_the_whole_list(app, shops):
    """The bug this guards: distance ordering happens in Python, so slicing in
    SQL first and sorting the slice orders each page correctly and the list as
    a whole wrongly -- page 2 could hold a shop nearer than anything on page 1.

    All three sit inside the first rung, so the ladder is not what is being
    measured here; only the order of the slices is.
    """
    shops("Far", NEAR_8KM)
    shops("Near", OGBA)
    shops("Mid", NEAR_5KM)

    def page(n):
        return _names(
            _search(
                app,
                shops,
                latitude=IKEJA[0],
                longitude=IKEJA[1],
                sort_by="nearby",
                per_page=1,
                page=n,
            )
        )

    assert page(1) == ["Near"]
    assert page(2) == ["Mid"]
    assert page(3) == ["Far"]


def test_the_ladder_widens_when_a_rung_is_too_thin_to_fill_a_page(app, shops):
    """One shop within 10 km and more just outside it should not render as a
    one-shop marketplace."""
    shops("Ogba", OGBA)
    shops("Lekki", LEKKI)

    result = _search(
        app,
        shops,
        latitude=IKEJA[0],
        longitude=IKEJA[1],
        sort_by="nearby",
        per_page=10,
    )
    assert result["location"]["radius_km"] == 50.0
    assert _names(result) == ["Ogba", "Lekki"]


def test_an_unlocated_shop_is_not_claimed_to_be_nearby(app, shops):
    """Most sellers have no coordinates yet. They must not be ranked as if
    they were next door -- they are simply not in a proximity list."""
    shops("Nowhere", None)
    shops("Ogba", OGBA)

    result = _search(
        app, shops, latitude=IKEJA[0], longitude=IKEJA[1], sort_by="nearby"
    )
    assert _names(result) == ["Ogba"]

    # ...but they are still discoverable when not browsing by distance.
    everything = _search(app, shops)
    assert "Nowhere" in _names(everything)


# ---------------------------------------------------------------------------
# Degrading gracefully
# ---------------------------------------------------------------------------


def test_nearby_without_a_location_falls_back_instead_of_failing(app, shops):
    """A denied location permission must not break browsing."""
    shops("Ogba", OGBA)
    result = _search(app, shops, sort_by="nearby")

    assert result["location"]["applied"] is False
    assert _names(result) == ["Ogba"]
    assert result["shops"][0]["distance_km"] is None


def test_zero_zero_is_not_a_location(app, shops):
    """(0, 0) is what a failed geocode looks like, not a shopper in the Gulf
    of Guinea."""
    shops("Ogba", OGBA)
    result = _search(app, shops, latitude=0.0, longitude=0.0, sort_by="nearby")
    assert result["location"]["applied"] is False


# ---------------------------------------------------------------------------
# Filters and payload
# ---------------------------------------------------------------------------


def test_filtering_by_category_works_at_all(app, shops, category):
    """`Seller.category` does not exist and never has -- every request with a
    category raised AttributeError, which the service's broad `except` turned
    into a 500 reading "Failed to search shops"."""
    shops("Tagged", OGBA, categories=[category.id])
    shops("Untagged", OGBA)

    result = _search(app, shops, category=category.slug)
    assert _names(result) == ["Tagged"]


def test_filtering_by_category_matches_the_name_too(app, shops, category):
    """The chips in the UI send whichever the categories endpoint gave them."""
    shops("Tagged", OGBA, categories=[category.id])
    # name and slug are the same string for this fixture, so ask by name.
    result = _search(app, shops, category=category.slug.upper().lower())
    assert _names(result) == ["Tagged"]


def test_the_banner_is_in_the_payload(app, shops):
    shops("Banner", OGBA, banner="https://cdn.example/banner.jpg")
    result = _search(app, shops)
    assert result["shops"][0]["banner_url"] == "https://cdn.example/banner.jpg"


def test_a_shop_without_a_banner_reports_none_rather_than_omitting_it(app, shops):
    shops("Plain", OGBA)
    result = _search(app, shops)
    assert result["shops"][0]["banner_url"] is None
