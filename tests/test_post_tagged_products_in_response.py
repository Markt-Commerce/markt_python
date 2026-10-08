"""Tagged products must come back on a post.

They were saved on create but never returned: PostDetailSchema declared
`products`, the model's relationship is `tagged_products`, and marshmallow
silently drops a field whose attribute does not exist. Pure schema tests --
no app, no database.
"""

from types import SimpleNamespace

from app.socials.schemas import (
    NichePostSchema,
    PostDetailSchema,
    PostDetailSearchResultSchema,
)


def _post(tagged=()):
    return SimpleNamespace(
        id="PST_TEST0001",
        user_id="USR_TEST0001",
        caption="Fresh bush pear",
        created_at=None,
        like_count=0,
        comment_count=0,
        niche_context={},
        categories=[],
        social_media=[],
        user=None,
        status=None,
        tagged_products=[SimpleNamespace(product_id=pid) for pid in tagged],
    )


def test_detail_returns_tagged_products():
    dumped = PostDetailSchema().dump(_post(["PRD_AAAA0001", "PRD_BBBB0002"]))
    assert dumped["products"] == [
        {"product_id": "PRD_AAAA0001"},
        {"product_id": "PRD_BBBB0002"},
    ]


def test_untagged_post_returns_an_empty_list_not_a_missing_key():
    # A missing key is what the bug looked like from the client, so an
    # untagged post must say so explicitly.
    assert PostDetailSchema().dump(_post())["products"] == []


def test_list_and_niche_responses_carry_tags_too():
    post = _post(["PRD_AAAA0001"])
    listed = PostDetailSearchResultSchema().dump({"items": [post], "pagination": {}})
    assert listed["items"][0]["products"] == [{"product_id": "PRD_AAAA0001"}]

    niche = NichePostSchema().dump(SimpleNamespace(post=post))
    assert niche["post"]["products"] == [{"product_id": "PRD_AAAA0001"}]


def test_create_payload_still_loads_products():
    # The create schema is separate and untouched; the client keeps sending
    # the same `products` shape it gets back.
    from app.socials.schemas import PostCreateSchema

    loaded = PostCreateSchema().load({"products": [{"product_id": "PRD_AAAA0001"}]})
    assert loaded["products"] == [{"product_id": "PRD_AAAA0001"}]
