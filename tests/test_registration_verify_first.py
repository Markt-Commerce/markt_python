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

from app.gamification.models import PointsLedger, UserStats
from app.users.models import Buyer, Seller, User, UserAddress
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
            # Everything that holds a foreign key into users and gets written
            # during these flows. Signing in awards points, which creates
            # ledger and stats rows -- so a test that logs in could not be
            # torn down until those were included here.
            for model, column in (
                (PointsLedger, PointsLedger.user_id),
                (UserStats, UserStats.user_id),
                (UserAddress, UserAddress.user_id),
                (Buyer, Buyer.user_id),
                (Seller, Seller.user_id),
            ):
                db.session.query(model).filter(column == user.id).delete(
                    synchronize_session=False
                )
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


# ---------------------------------------------------------------------------
# Choosing a handle after the fact
# ---------------------------------------------------------------------------


def test_the_minted_username_can_be_changed(client, created, sent):
    """The signup screen that asks for a handle now runs after the account
    exists, so PATCH /users/profile has to accept one -- otherwise the field
    would be collected and dropped, which is the bug this whole reordering is
    meant to stop repeating."""
    email, resp = _register(client, created)
    minted = resp.get_json()["username"]

    handle = f"ada{uuid.uuid4().hex[:8]}"
    changed = client.patch(f"{API}/profile", json={"username": handle})

    assert changed.status_code == 200, changed.get_data(as_text=True)
    assert changed.get_json()["username"] == handle != minted


def test_a_taken_username_is_refused_rather_than_swapped(client, created, sent):
    first_email, first = _register(client, created)
    taken = first.get_json()["username"]

    _register(client, created)  # logs the client in as the second account
    clash = client.patch(f"{API}/profile", json={"username": taken})

    assert clash.status_code == 409, clash.get_data(as_text=True)


def test_a_reserved_username_is_refused(client, created, sent):
    _register(client, created)
    resp = client.patch(f"{API}/profile", json={"username": "admin"})
    assert resp.status_code == 409, resp.get_data(as_text=True)


def test_keeping_your_own_username_is_not_a_conflict(client, created, sent):
    """Re-submitting an unchanged form must not collide with itself."""
    email, resp = _register(client, created)
    mine = resp.get_json()["username"]

    again = client.patch(f"{API}/profile", json={"username": mine})
    assert again.status_code == 200, again.get_data(as_text=True)


# ---------------------------------------------------------------------------
# One inbox, one account
# ---------------------------------------------------------------------------


def test_the_same_address_in_different_case_is_the_same_account(client, created, sent):
    """Reported from a device: signing up twice with the same address produced
    two unrelated accounts — one buyer, one seller — because the second time
    it was typed with a capital letter.

    `users.email` is unique over the *string*, so "Ada@x.com" and "ada@x.com"
    were two different rows and the duplicate check never fired.
    """
    email = _email()
    _, first = _register(client, created, email=email)
    assert first.status_code == 201

    shouty = email.upper()
    created.append(shouty.lower())
    second = client.post(
        f"{API}/register",
        json={
            "email": shouty,
            "password": "Passw0rdy",
            "account_type": "seller",
        },
    )
    assert second.status_code == 409, second.get_data(as_text=True)


def test_the_stored_address_is_lowercased(client, created, sent, app):
    email = _email()
    created.append(email)
    resp = client.post(
        f"{API}/register",
        json={
            "email": email.upper(),
            "password": "Passw0rdy",
            "account_type": "buyer",
        },
    )
    assert resp.status_code == 201
    assert resp.get_json()["email"] == email

    with app.app_context():
        assert db.session.query(User).filter(User.email == email).first() is not None


def test_signing_in_with_a_different_case_reaches_the_same_account(
    client, created, sent
):
    """The other half of the bug: an account made in lower case had to be
    signed into in lower case, or it looked like it did not exist."""
    email = _email()
    _, resp = _register(client, created, email=email)
    assert resp.status_code == 201

    code = [m for m in sent if m["email"] == email][-1]["code"]
    client.post(
        f"{API}/email-verification/verify",
        json={"email": email, "verification_code": code},
    )

    signed_in = client.post(
        f"{API}/login",
        json={
            "email": email.upper(),
            "password": "Passw0rdy",
            "account_type": "buyer",
        },
    )
    assert signed_in.status_code == 200, signed_in.get_data(as_text=True)
    assert signed_in.get_json()["email"] == email


def test_surrounding_whitespace_is_not_a_different_address(client, created, sent):
    """A pasted address often carries a trailing space."""
    email = _email()
    _, first = _register(client, created, email=email)
    assert first.status_code == 201

    second = client.post(
        f"{API}/register",
        json={
            "email": f"  {email} ",
            "password": "Passw0rdy",
            "account_type": "buyer",
        },
    )
    assert second.status_code == 409, second.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Opening a shop from an account that is already a buyer
# ---------------------------------------------------------------------------


def test_a_new_shop_inherits_the_address_the_user_already_gave(
    client, created, sent, app
):
    """The Create Seller sheet asks for a name, a description and categories —
    and nothing about where the shop is. A shop with no coordinates never
    appears in a proximity search, so every shop opened that way would have
    been invisible on the Nearest tab.

    The buyer already typed an address during signup; reusing it beats asking
    twice for something we know.
    """
    email, resp = _register(client, created)
    assert resp.status_code == 201

    code = [m for m in sent if m["email"] == email][-1]["code"]
    client.post(
        f"{API}/email-verification/verify",
        json={"email": email, "verification_code": code},
    )
    client.patch(f"{API}/profile/buyer", json={"buyername": "Amaka Obi"})
    client.patch(
        f"{API}/address",
        json={
            "street": "12 Allen Avenue",
            "city": "Ikeja",
            "state": "Lagos",
            "country": "Nigeria",
            "latitude": 6.6018,
            "longitude": 3.3515,
        },
    )

    made = client.post(
        f"{API}/create-seller",
        json={
            "shop_name": "Amaka Fabrics",
            "description": "Ankara and lace.",
            "category_ids": [],
        },
    )
    assert made.status_code == 201, made.get_data(as_text=True)

    with app.app_context():
        user = db.session.query(User).filter(User.email == email).first()
        seller = db.session.query(Seller).filter(Seller.user_id == user.id).first()
        assert seller.shop_latitude == pytest.approx(6.6018)
        assert seller.shop_longitude == pytest.approx(3.3515)
        assert seller.shop_slug, "a shop opened this way still needs a slug"


def test_a_shop_is_not_given_a_location_we_do_not_have(client, created, sent, app):
    """No address, no coordinates — rather than (0, 0), which would place every
    such shop in the Gulf of Guinea and rank it as equidistant from Lagos."""
    email, resp = _register(client, created)
    code = [m for m in sent if m["email"] == email][-1]["code"]
    client.post(
        f"{API}/email-verification/verify",
        json={"email": email, "verification_code": code},
    )

    made = client.post(
        f"{API}/create-seller",
        json={
            "shop_name": "Unlocated Shop",
            "description": "No address given.",
            "category_ids": [],
        },
    )
    assert made.status_code == 201, made.get_data(as_text=True)

    with app.app_context():
        user = db.session.query(User).filter(User.email == email).first()
        seller = db.session.query(Seller).filter(Seller.user_id == user.id).first()
        assert seller.shop_latitude is None
        assert seller.shop_longitude is None
