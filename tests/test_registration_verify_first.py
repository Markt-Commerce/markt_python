"""Registration against a real database, over HTTP.

The change under test is an ordering change, and ordering bugs do not show up
in a mocked session -- they show up when the second request depends on what
the first one actually committed. So this drives the real endpoints against a
real Postgres:

    POST /users/register          (email + password + role, nothing else)
    POST /users/email-verification/verify
    PATCH /users/profile/buyer    (or /seller)

Gated on RUN_DB_TESTS=1 like the other real-database tests: it writes rows, so
it must never point at whatever DB_* a developer's settings.ini happens to
name. See tests/test_inventory_concurrency.py for the full reasoning.
"""

import os
import uuid
from unittest.mock import patch

import pytest

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

API = "/api/v1/users"


@pytest.fixture(scope="module")
def app():
    flask_app = create_flask_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    return flask_app


@pytest.fixture
def created(app):
    """Tracks the emails this test made so they can be removed afterwards.

    Deleting by email rather than truncating: this database is disposable, but
    a test that truncates tables is a test that cannot be run next to anything
    else, and these want to be runnable against a dev database that has data
    in it.
    """
    emails = []
    yield emails
    with app.app_context():
        for email in emails:
            user = db.session.query(User).filter(User.email == email).first()
            if not user:
                continue
            db.session.query(Buyer).filter(Buyer.user_id == user.id).delete()
            db.session.query(Seller).filter(Seller.user_id == user.id).delete()
            db.session.delete(user)
        db.session.commit()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sent():
    """Captures verification emails instead of sending them.

    The suite must never hit Resend -- settings.ini carries a live API key,
    and a test run should not mail anyone. Capturing also gives the tests the
    code, which is the only way to drive the verify step honestly.
    """
    outbox = []

    def fake_send(email, verification_code, username=None, **kw):
        outbox.append({"email": email, "code": verification_code})
        return True

    with patch(
        "app.libs.email_service.email_service.send_verification_email",
        side_effect=fake_send,
    ):
        yield outbox


def _email():
    return f"test-{uuid.uuid4().hex[:10]}@markt.test"


def _register(client, created, email=None, account_type="buyer", **extra):
    email = email or _email()
    created.append(email)
    body = {"email": email, "password": "Passw0rdy", "account_type": account_type}
    body.update(extra)
    return email, client.post(f"{API}/register", json=body)


# ---------------------------------------------------------------------------
# The first screen is enough to make an account
# ---------------------------------------------------------------------------


def test_email_and_password_alone_create_an_account(client, created, sent):
    """No username, no name, no shop, no address -- the whole point.

    Before this, register demanded a username and a full buyer/seller block,
    which is why the app had to collect four screens of data before it could
    call the API at all.
    """
    email, resp = _register(client, created)

    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["email"] == email
    assert body["username"], "a username should have been minted"
    assert body.get("access_token"), "the client needs a token to finish signup"


def test_the_account_is_reachable_and_unverified(client, created, sent, app):
    email, resp = _register(client, created)
    assert resp.status_code == 201

    with app.app_context():
        user = db.session.query(User).filter(User.email == email).first()
        assert user is not None, "register must commit, not just respond"
        assert user.email_verified is False
        assert user.is_buyer is True
        buyer = db.session.query(Buyer).filter(Buyer.user_id == user.id).first()
        # The row has to exist even though it is empty: `is_buyer` with no
        # Buyer row is where every "Buyer account not found" bug comes from,
        # and the PATCH that fills it in needs something to update.
        assert buyer is not None
        assert not buyer.buyername


def test_the_code_is_sent_by_register_itself(client, created, sent):
    """It used to be sent only when the verification screen mounted, four
    screens later, after the profile picture step."""
    email, resp = _register(client, created)
    assert resp.status_code == 201
    assert [m for m in sent if m["email"] == email], "no verification code sent"


def test_the_response_says_to_verify_next(client, created, sent):
    _email_, resp = _register(client, created)
    assert resp.get_json()["onboarding"] == {
        "email_verified": False,
        "profile_complete": False,
        "next_step": "verify_email",
    }


# ---------------------------------------------------------------------------
# Failures land on the field that caused them
# ---------------------------------------------------------------------------


def test_a_duplicate_email_fails_on_the_first_screen(client, created, sent):
    """The bug this reordering exists to kill.

    The address was only checked once registration ran, which was after name,
    phone, shop details and address had been typed -- and it surfaced as
    "Failed to complete registration. Please try again." with no way to fix
    it short of backing out three screens.
    """
    email, first = _register(client, created)
    assert first.status_code == 201

    _, second = _register(client, created, email=email)
    assert second.status_code in (400, 409), second.get_data(as_text=True)
    assert "email" in second.get_json()["message"].lower()


def test_a_mail_outage_does_not_destroy_the_account(client, created):
    """The account is committed before the send. A provider failure must cost
    the user a tap on "resend", not their registration."""
    with patch(
        "app.libs.email_service.email_service.send_verification_email",
        side_effect=RuntimeError("resend is down"),
    ):
        email, resp = _register(client, created)

    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert resp.get_json()["onboarding"]["next_step"] == "verify_email"


def test_a_supplied_username_is_still_honoured_and_still_guarded(client, created, sent):
    """Optional does not mean ignored: a client that has one must get it, and
    must still be told when it is taken."""
    handle = f"ada{uuid.uuid4().hex[:8]}"
    email, resp = _register(client, created, username=handle)
    assert resp.status_code == 201
    assert resp.get_json()["username"] == handle

    _, clash = _register(client, created, username=handle)
    assert clash.status_code in (400, 409)
    assert "username" in clash.get_json()["message"].lower()


def test_two_accounts_from_the_same_address_get_different_usernames(
    client, created, sent
):
    """Minted handles are derived from the email local part, so ada@a.com and
    ada@b.com both seed "ada"."""
    a, ra = _register(client, created, email=f"ada-{uuid.uuid4().hex[:6]}@one.test")
    b, rb = _register(client, created, email=f"ada-{uuid.uuid4().hex[:6]}@two.test")
    assert ra.status_code == rb.status_code == 201
    assert ra.get_json()["username"] != rb.get_json()["username"]


# ---------------------------------------------------------------------------
# Verify, then finish the profile
# ---------------------------------------------------------------------------


def test_the_full_buyer_journey(client, created, sent, app):
    email, resp = _register(client, created)
    assert resp.status_code == 201

    code = [m for m in sent if m["email"] == email][-1]["code"]
    verified = client.post(
        f"{API}/email-verification/verify",
        json={"email": email, "verification_code": code},
    )
    assert verified.status_code == 200, verified.get_data(as_text=True)

    named = client.patch(f"{API}/profile/buyer", json={"buyername": "Ada Obi"})
    assert named.status_code == 200, named.get_data(as_text=True)

    body = named.get_json()
    assert body["onboarding"] == {
        "email_verified": True,
        "profile_complete": True,
        "next_step": None,
    }
    assert body["buyer_account"]["buyername"] == "Ada Obi"


def test_the_full_seller_journey_mints_a_shop_slug(client, created, sent, app):
    """shop_slug is a unique column that nothing ever wrote -- registration
    left it NULL for every seller ever created. Naming the shop is now where
    it comes from."""
    email, resp = _register(client, created, account_type="seller")
    assert resp.status_code == 201

    code = [m for m in sent if m["email"] == email][-1]["code"]
    client.post(
        f"{API}/email-verification/verify",
        json={"email": email, "verification_code": code},
    )

    shop = client.patch(
        f"{API}/profile/seller",
        json={"shop_name": "Ada Fabrics", "description": "Ankara and lace."},
    )
    assert shop.status_code == 200, shop.get_data(as_text=True)
    body = shop.get_json()
    assert body["onboarding"]["next_step"] is None

    with app.app_context():
        user = db.session.query(User).filter(User.email == email).first()
        seller = db.session.query(Seller).filter(Seller.user_id == user.id).first()
        assert seller.shop_slug, "naming the shop should have minted a slug"
        assert seller.shop_slug.startswith("ada-fabrics")


def test_an_unverified_account_still_knows_where_to_resume(client, created, sent):
    """The interruption case. Someone who closed the app after the first
    screen comes back, and the profile response tells the router where to go
    rather than the client guessing from blank fields."""
    email, resp = _register(client, created)
    assert resp.status_code == 201

    profile = client.get(f"{API}/profile")
    assert profile.status_code == 200
    assert profile.get_json()["onboarding"]["next_step"] == "verify_email"
