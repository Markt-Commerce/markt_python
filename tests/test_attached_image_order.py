"""Photos come back in the order they were attached.

Every link table already carries a `sort_order`, and every writer fills it
in from the position the photo was picked in. Only products read it back:
Request.images and Post.social_media had no `order_by`, so Postgres
returned rows in whatever order it found them -- usually insertion order,
never promised to be, and free to change the moment a row is updated or the
table is vacuumed.

On a buyer request that is the whole meaning of the photos: "here is the
plug end, here is the socket end" is not the same request the other way
round.

The structural checks run anywhere. The ordering check needs a real
database, because this is entirely a question of what SQL comes back.
"""

import os
import uuid

import pytest

from app.media.models import RequestImage
from app.requests.models import BuyerRequest
from app.socials.models import Post
from app.users.models import Buyer, User
from external.database import db
from main.setup import create_flask_app


class TestTheRelationshipsDeclareAnOrder:
    """Cheap, runs everywhere, and catches the order_by being dropped."""

    def test_request_images_are_ordered(self):
        assert (
            BuyerRequest.images.property.order_by
        ), "Request.images has no order_by: sort_order is written and never read"

    def test_post_media_is_ordered(self):
        assert (
            Post.social_media.property.order_by
        ), "Post.social_media has no order_by: sort_order is written and never read"

    def test_they_order_by_sort_order_specifically(self):
        for rel, column in (
            (BuyerRequest.images, "sort_order"),
            (Post.social_media, "sort_order"),
        ):
            names = [str(c) for c in rel.property.order_by]
            assert any(column in n for n in names), names


@pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason=(
        "requires a disposable database; set RUN_DB_TESTS=1 only when DB_* "
        "points at a throwaway Postgres instance"
    ),
)
class TestTheOrderSurvivesTheRoundTrip:
    @pytest.fixture(scope="class")
    def app(self):
        flask_app = create_flask_app()
        flask_app.config["TESTING"] = True
        return flask_app

    def test_photos_read_back_in_the_order_they_were_attached(self, app):
        with app.app_context():
            tag = uuid.uuid4().hex[:8]
            user = User(
                email=f"o.{tag}@markt-test.example.com",
                username=f"o{tag}",
                email_verified=True,
                is_buyer=True,
            )
            db.session.add(user)
            db.session.flush()
            db.session.add(Buyer(user_id=user.id, buyername="Order Test"))

            request = BuyerRequest(
                user_id=user.id,
                title="USB-C to 3.5mm adapter",
                description="Reference photos attached, in order.",
            )
            db.session.add(request)
            db.session.flush()

            # Inserted deliberately out of order: if the read is really
            # ordered by sort_order, insertion order cannot be what makes
            # this pass.
            from app.media.models import Media, MediaType

            media = []
            for i in range(3):
                m = Media(user_id=user.id, media_type=MediaType.IMAGE)
                db.session.add(m)
                db.session.flush()
                media.append(m)

            for sort_order, m in ((2, media[0]), (0, media[1]), (1, media[2])):
                db.session.add(
                    RequestImage(
                        request_id=request.id,
                        media_id=m.id,
                        is_primary=(sort_order == 0),
                        sort_order=sort_order,
                    )
                )
            db.session.commit()
            request_id = request.id
            expected = [media[1].id, media[2].id, media[0].id]

            db.session.expire_all()
            fresh = db.session.get(BuyerRequest, request_id)
            assert [i.media_id for i in fresh.images] == expected

            db.session.query(RequestImage).filter_by(request_id=request_id).delete()
            db.session.delete(fresh)
            for m in media:
                db.session.delete(db.session.get(Media, m.id))
            db.session.query(Buyer).filter_by(user_id=user.id).delete()
            db.session.delete(db.session.get(User, user.id))
            db.session.commit()
