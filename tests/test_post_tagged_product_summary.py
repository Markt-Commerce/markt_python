"""A tagged product comes back as a card, not just an id.

The app used to fetch /products/{id} for every tag on every post it opened.
Pure schema / query-construction tests: no app, no database.
"""

from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import joinedload

from app.socials.models import Post, PostProduct
from app.socials.schemas import PostCreateSchema, PostDetailSchema
from app.socials.services import _tagged_product_card


def _product(available=True, images=True, seller=True):
    media = SimpleNamespace(get_url=lambda: "https://cdn.example/p1.jpg")
    return SimpleNamespace(
        id="PRD_AAAA0001",
        name="Bush pear, 1kg",
        price=2500.00,
        images=[SimpleNamespace(media=media)] if images else [],
        seller=SimpleNamespace(shop_name="Ameth Farms") if seller else None,
        is_available=lambda: available,
    )


def _post(tags):
    return SimpleNamespace(
        id="PST_TEST0001",
        user_id="USR_TEST0001",
        caption="Fresh",
        created_at=None,
        like_count=0,
        comment_count=0,
        niche_context={},
        categories=[],
        social_media=[],
        user=None,
        status=None,
        tagged_products=tags,
    )


def _tag(product):
    return SimpleNamespace(
        product_id=product.id if product else "PRD_GONE0001", product=product
    )


def test_tag_carries_the_product_card():
    products = PostDetailSchema().dump(_post([_tag(_product())]))["products"]
    assert products == [
        {
            "product_id": "PRD_AAAA0001",
            "product": {
                "id": "PRD_AAAA0001",
                "name": "Bush pear, 1kg",
                "price": 2500.0,
                "image_url": "https://cdn.example/p1.jpg",
                "shop_name": "Ameth Farms",
                "is_available": True,
            },
        }
    ]


def test_sold_out_product_says_so():
    card = PostDetailSchema().dump(_post([_tag(_product(available=False))]))[
        "products"
    ][0]["product"]
    assert card["is_available"] is False


def test_missing_image_and_seller_are_null_not_errors():
    card = PostDetailSchema().dump(_post([_tag(_product(images=False, seller=False))]))[
        "products"
    ][0]["product"]
    assert card["image_url"] is None
    assert card["shop_name"] is None


def test_deleted_product_keeps_the_id_and_a_null_card():
    tags = PostDetailSchema().dump(_post([_tag(None)]))["products"]
    assert tags == [{"product_id": "PRD_GONE0001", "product": None}]


def test_create_payload_is_unchanged():
    loaded = PostCreateSchema().load({"products": [{"product_id": "PRD_AAAA0001"}]})
    assert loaded["products"] == [{"product_id": "PRD_AAAA0001"}]


def test_eager_load_paths_are_valid():
    # Compiling against the Postgres dialect validates every relationship in
    # the option chain without connecting to anything.
    stmt = select(Post).options(
        joinedload(Post.tagged_products).joinedload(PostProduct.product),
        *_tagged_product_card(
            joinedload(Post.tagged_products).joinedload(PostProduct.product)
        ),
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "products" in sql and "sellers" in sql


def test_feed_post_carries_the_same_tags_as_the_detail():
    from app.socials.services import _feed_post_products

    post = _post([_tag(_product())])
    assert _feed_post_products(post) == PostDetailSchema().dump(post)["products"]


def test_feed_post_without_tags_is_an_empty_list():
    from app.socials.services import _feed_post_products

    assert _feed_post_products(_post([])) == []


def test_a_broken_tag_never_drops_the_feed_post():
    from app.socials.services import _feed_post_products

    class Exploding:
        id = "PST_TEST0001"

        @property
        def tagged_products(self):
            raise RuntimeError("lazy load outside a session")

    assert _feed_post_products(Exploding()) == []
