"""What stops "create the account first" from being a squatting hole.

Creating the account before the code is entered is the standard shape and the
only one that survives an interrupted signup -- the code has to attach to
something. The objection to it is real though: nothing stops someone typing an
address they do not own.

Three things make that safe, and these test all three:

  * an unverified account cannot sign in (already true, and tested in
    test_email_verification.py)
  * an unverified account cannot do anything, so there is nothing to squat
    *with*
  * the person who actually owns the inbox can always take the address back,
    because an account that never verified has no claim on it

Gated on RUN_DB_TESTS=1 like the other real-database tests.
"""

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.gamification.models import PointsLedger, UserStats
from app.libs.errors import UnverifiedEmailError
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
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def created(app):
    emails = []
    yield emails
    with app.app_context():
        for email in emails:
            user = db.session.query(User).filter(User.email == email).first()
            if not user:
                continue
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


@pytest.fixture(autouse=True)
def sent():
    """Captures verification emails instead of sending them.

    Never reaches Resend -- settings.ini carries a live key. Capturing also
    gives the tests the code, which is the only way to drive verification
    honestly.
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
    return f"squat-{uuid.uuid4().hex[:10]}@markt.test"


def _register(client, created, email, account_type="buyer"):
    created.append(email)
    return client.post(
        f"{API}/register",
        json={"email": email, "password": "Passw0rdy", "account_type": account_type},
    )


# ---------------------------------------------------------------------------
# The owner can always take their address back
# ---------------------------------------------------------------------------


def test_an_address_nobody_verified_can_be_claimed_by_whoever_owns_it(
    client, created, app
):
    """The squatting case. Someone signs up with an address they do not own
    and never verifies it; the real owner must not be locked out forever."""
    email = _email()
    first = _register(client, created, email)
    assert first.status_code == 201
    squatter_id = first.get_json()["id"]

    second = _register(client, created, email, account_type="seller")
    assert second.status_code == 201, second.get_data(as_text=True)
    assert second.get_json()["id"] != squatter_id

    with app.app_context():
        # Exactly one account holds the address afterwards.
        assert db.session.query(User).filter(User.email == email).count() == 1
        assert db.session.query(User).filter(User.id == squatter_id).first() is None


def test_a_verified_account_is_never_taken_over(client, created, app):
    """The case that matters. Once someone has proved they own the address,
    registering it again is refused -- that is what the 409 is for."""
    email = _email()
    assert _register(client, created, email).status_code == 201

    with app.app_context():
        user = db.session.query(User).filter(User.email == email).first()
        user.email_verified = True
        db.session.commit()
        verified_id = user.id

    again = _register(client, created, email)
    assert again.status_code == 409, again.get_data(as_text=True)

    with app.app_context():
        assert (
            db.session.query(User).filter(User.email == email).first().id == verified_id
        )


def test_reclaiming_removes_the_profile_row_too(client, created, app):
    """`is_buyer` with an orphaned Buyer row is the state every "Buyer account
    not found" bug comes from."""
    email = _email()
    assert _register(client, created, email).status_code == 201
    with app.app_context():
        old = db.session.query(User).filter(User.email == email).first()
        old_buyer = db.session.query(Buyer).filter(Buyer.user_id == old.id).first()
        assert old_buyer is not None
        old_buyer_id = old_buyer.id

    assert _register(client, created, email, account_type="seller").status_code == 201

    with app.app_context():
        assert db.session.query(Buyer).filter(Buyer.id == old_buyer_id).first() is None


# ---------------------------------------------------------------------------
# An unverified account cannot do anything
# ---------------------------------------------------------------------------


def _as(user):
    """Patch flask_login's current_user to `user` for a decorator test."""
    return patch("app.libs.decorators.current_user", user)


def _decorated(decorator):
    from app.libs import decorators

    @getattr(decorators, decorator)
    def endpoint():
        return "reached"

    return endpoint


@pytest.mark.parametrize("decorator", ["buyer_required", "seller_required"])
def test_an_unverified_account_is_refused(decorator, app):
    user = MagicMock()
    user.is_authenticated = True
    user.is_buyer = True
    user.is_seller = True
    user.seller_account = MagicMock(is_active=True)
    user.email_verified = False
    user.email = "squatter@markt.test"

    with app.app_context(), _as(user):
        with pytest.raises(UnverifiedEmailError) as caught:
            _decorated(decorator)()

    # 403, not 401 -- the session is valid, the account just is not allowed
    # yet, and 401 is the status every client treats as "sign out".
    assert caught.value.status_code == 403
    assert caught.value.payload["error_type"] == "unverified_email"


@pytest.mark.parametrize("decorator", ["buyer_required", "seller_required"])
def test_a_verified_account_passes(decorator, app):
    user = MagicMock()
    user.is_authenticated = True
    user.is_buyer = True
    user.is_seller = True
    user.seller_account = MagicMock(is_active=True)
    user.email_verified = True

    with app.app_context(), _as(user):
        assert _decorated(decorator)() == "reached"


def test_register_hands_over_no_credentials(client, created):
    """The strongest form of "an unverified account cannot do anything".

    It used to be enforced by decorators, which meant the account held a
    working token and was trusted not to use it anywhere that mattered. Now
    it holds nothing at all: the verify endpoint is what issues credentials,
    so proving you own the address is the thing that buys access rather than
    a step the client is trusted to honour.

    (This replaces a test asserting the profile could still be filled in
    while unverified. That ordering no longer exists -- verification now
    comes before the profile step, on the client and on the server.)
    """
    email = _email()
    resp = _register(client, created, email)
    assert resp.status_code == 201
    assert not resp.get_json().get("access_token")

    # And nothing authenticated is reachable with what register handed back.
    assert client.get(f"{API}/profile").status_code == 401


def test_verifying_is_what_signs_you_in(client, created, sent):
    """Register sends the code, so this uses the one it actually sent rather
    than asking for another -- a resend inside 60 seconds is refused, which is
    the rate limit doing its job."""
    email = _email()
    assert _register(client, created, email).status_code == 201

    code = [m for m in sent if m["email"] == email][-1]["code"]
    verified = client.post(
        f"{API}/email-verification/verify",
        json={"email": email, "verification_code": code},
    )
    assert verified.status_code == 200, verified.get_data(as_text=True)
    body = verified.get_json()
    assert body["access_token"], "verifying is what issues the token"
    assert body["onboarding"]["email_verified"] is True

    # And the session it opened actually works.
    assert client.get(f"{API}/profile").status_code == 200
