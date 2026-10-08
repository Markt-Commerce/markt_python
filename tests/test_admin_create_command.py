"""``flask create-admin``: bootstrapping a staff account from the server.

``provision_admin`` runs against a mocked session, like the other admin
service tests; the click command is driven with CliRunner and the session
scope patched out.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from flask import Flask
from flask.cli import ScriptInfo

from app.admin.management.commands import create_admin as cmd
from app.admin.management.commands.create_admin import (
    AdminProvisionError,
    provision_admin,
)
from app.admin.permissions import is_staff, is_super_admin
from app.users.models import User

GOOD_PASSWORD = "Str0ngPass"


def _session(existing=None):
    """A session whose email lookup returns ``existing`` and whose username
    lookup finds nothing."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = existing
    return session


def _audit_rows(session):
    return [
        c.args[0]
        for c in session.add.call_args_list
        if type(c.args[0]).__name__ == "AdminAuditLog"
    ]


def _audit_actions(session):
    rows = _audit_rows(session)
    # actor_id is NOT NULL in the schema; a CLI grant has no signed-in staff
    # member, so the account itself must be named or the commit fails.
    assert all(r.actor_id for r in rows)
    return [r.action for r in rows]


# --- provision_admin ------------------------------------------------------


@patch("app.admin.management.commands.create_admin.unique_username")
def test_creates_verified_super_admin_without_buyer_or_seller(mock_username):
    mock_username.return_value = "ops1234"
    session = _session()
    # The real flush assigns the USR_ id the audit row points at.
    session.flush.side_effect = lambda: setattr(user_holder[0], "id", "USR_NEW")
    user_holder = []
    session.add.side_effect = lambda obj: (
        user_holder.append(obj) if isinstance(obj, User) else None
    )

    user, created = provision_admin(
        session, " Ops@Markt.co ", "super_admin", password=GOOD_PASSWORD
    )

    assert created is True
    assert user.email == "ops@markt.co"
    assert user.username == "ops1234"
    assert user.email_verified is True
    assert user.is_buyer is False and user.is_seller is False
    assert user.admin_role == "super_admin"
    assert is_staff(user) and is_super_admin(user)
    assert user.check_password(GOOD_PASSWORD)
    assert _audit_actions(session) == ["user.create_admin"]


def test_non_super_role_is_staff_but_not_super():
    user, _ = provision_admin(
        _session(), "s@markt.co", "support", password=GOOD_PASSWORD, username="sup"
    )
    assert user.username == "sup"
    assert is_staff(user) and not is_super_admin(user)


@pytest.mark.parametrize("weak", ["short1A", "alllowercase1", "NoDigitsHere"])
def test_weak_password_refused(weak):
    with pytest.raises(AdminProvisionError):
        provision_admin(_session(), "a@markt.co", "super_admin", password=weak)


def test_missing_password_refused_for_new_account():
    with pytest.raises(AdminProvisionError, match="password is required"):
        provision_admin(_session(), "a@markt.co", "super_admin")


def test_unknown_role_refused():
    with pytest.raises(ValueError):
        provision_admin(_session(), "a@markt.co", "owner", password=GOOD_PASSWORD)


def test_existing_account_refused_without_promote():
    existing = User(id="USR_1", email="a@markt.co", username="a")
    session = _session(existing)

    with pytest.raises(AdminProvisionError, match="--promote"):
        provision_admin(session, "a@markt.co", "super_admin", password=GOOD_PASSWORD)

    assert existing.admin_role is None
    session.add.assert_not_called()


def test_promote_grants_role_and_keeps_password():
    existing = User(id="USR_1", email="a@markt.co", username="a")
    existing.set_password("Original1x")
    session = _session(existing)

    user, created = provision_admin(session, "a@markt.co", "finance", promote=True)

    assert created is False and user is existing
    assert user.admin_role == "finance"
    assert user.check_password("Original1x")
    assert _audit_actions(session) == ["user.role_change"]


def test_deleted_account_is_never_promoted():
    from datetime import datetime

    existing = User(id="USR_1", email="a@markt.co", deleted_at=datetime.utcnow())
    with pytest.raises(AdminProvisionError, match="deleted"):
        provision_admin(_session(existing), "a@markt.co", "super_admin", promote=True)
    assert existing.admin_role is None


# --- click command --------------------------------------------------------


def _invoke(args, existing=None, input=None, env=None):
    session = _session(existing)

    @contextmanager
    def scope():
        yield session

    # with_appcontext needs an app; the command body touches none of it once
    # the session is patched, so a bare Flask app is enough.
    app = Flask(__name__)
    runner = CliRunner(env=env)
    with patch.object(cmd, "session_scope", scope), patch.object(
        cmd, "unique_username", return_value="ops1234"
    ):
        result = runner.invoke(
            cmd.create_admin,
            args,
            input=input,
            obj=ScriptInfo(create_app=lambda *a, **k: app),
        )
    return result, session


def test_cli_prompts_for_hidden_confirmed_password():
    result, _ = _invoke(
        ["--email", "ops@markt.co"], input=f"{GOOD_PASSWORD}\n{GOOD_PASSWORD}\n"
    )
    assert result.exit_code == 0, result.output
    assert "Created super_admin ops@markt.co" in result.output
    assert GOOD_PASSWORD not in result.output


def test_cli_reads_password_from_env():
    result, _ = _invoke(
        ["--email", "ops@markt.co", "--role", "support"],
        env={"MARKT_ADMIN_PASSWORD": GOOD_PASSWORD},
    )
    assert result.exit_code == 0, result.output
    assert "Created support ops@markt.co" in result.output


def test_cli_reports_refusal_without_traceback():
    existing = User(id="USR_1", email="a@markt.co", username="a")
    result, _ = _invoke(
        ["--email", "a@markt.co"],
        existing=existing,
        env={"MARKT_ADMIN_PASSWORD": GOOD_PASSWORD},
    )
    assert result.exit_code == 1
    assert "Error:" in result.output and "--promote" in result.output
    assert "Traceback" not in result.output


def test_cli_promote_does_not_ask_for_password():
    existing = User(id="USR_1", email="a@markt.co", username="a")
    result, _ = _invoke(["--email", "a@markt.co", "--promote"], existing=existing)
    assert result.exit_code == 0, result.output
    assert "Promoted super_admin a@markt.co" in result.output
    assert "Password" not in result.output
