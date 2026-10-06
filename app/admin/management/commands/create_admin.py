"""``flask create-admin``: provision a staff account from the server.

Staff standing has no self-serve path (see ``User.is_admin``); a super_admin
grants it from the console. That leaves the first super_admin on a fresh
database with nobody to grant it, which is the gap this closes -- run it once
on the box after ``flask db upgrade`` and sign in at the admin console.

The account is created email-verified with no buyer or seller profile: staff
sign in through ``AdminAuthService.login``, which needs neither.

An existing address is never taken over silently. ``--promote`` grants the role
to that account and leaves its password alone; without it the command refuses.
"""

import click
from flask.cli import with_appcontext
from marshmallow import ValidationError as SchemaValidationError

from app.admin.permissions import AdminRole
from app.admin.services import AdminAuditService
from app.libs.session import session_scope
from app.users.models import User
from app.users.schemas import UserRegisterSchema
from app.users.services import unique_username

ROLE_CHOICES = [role.value for role in AdminRole]

# The audit log requires an actor, and a shell on the server has no signed-in
# staff member to name. The account itself stands in; this reason is what
# tells a reader the grant came from the box rather than the console.
CLI_REASON = "flask create-admin (server CLI)"


class AdminProvisionError(Exception):
    """A refusal the operator can act on, shown without a traceback."""


def validate_password(password: str) -> None:
    """The customer signup rules, so staff passwords are no weaker."""
    try:
        UserRegisterSchema().fields["password"].deserialize(password)
    except SchemaValidationError as e:
        raise AdminProvisionError(" ".join(e.messages)) from e


def provision_admin(
    session,
    email: str,
    role: str,
    password: str = None,
    username: str = None,
    promote: bool = False,
):
    """Create a staff account, or grant ``role`` to an existing one.

    Returns ``(user, created)``. Writes on the caller's session together with
    an audit row, so the account and its record of creation commit as one.
    """
    email = email.strip().lower()
    AdminRole(role)  # unknown roles fail here rather than granting nothing

    user = session.query(User).filter(User.email == email).first()
    if user:
        if user.deleted_at:
            raise AdminProvisionError(f"{email} belongs to a deleted account.")
        if not promote:
            raise AdminProvisionError(
                f"{email} already has an account. Re-run with --promote to "
                f"grant it the {role} role (its password is left unchanged)."
            )
        before = {"admin_role": user.admin_role}
        user.admin_role = role
        AdminAuditService.record(
            session,
            user,
            "user.role_change",
            target_type="user",
            target_id=user.id,
            reason=f"{CLI_REASON} --promote",
            before=before,
            after={"admin_role": role},
        )
        return user, False

    if not password:
        raise AdminProvisionError("A password is required for a new account.")
    validate_password(password)

    username = (username or "").strip()
    if username:
        if session.query(User).filter(User.username == username).first():
            raise AdminProvisionError(f"Username {username!r} is already taken.")
    else:
        username = unique_username(session, email)

    user = User(
        email=email,
        username=username,
        is_buyer=False,
        is_seller=False,
        is_active=True,
        # Created by an operator on the server, not through a signup the
        # address owner could have mistyped.
        email_verified=True,
        admin_role=role,
    )
    user.set_password(password)
    session.add(user)
    session.flush()

    AdminAuditService.record(
        session,
        user,
        "user.create_admin",
        target_type="user",
        target_id=user.id,
        reason=CLI_REASON,
        after={"email": email, "admin_role": role},
    )
    return user, True


@click.command("create-admin")
@click.option("--email", prompt=True, help="Sign-in address for the account.")
@click.option(
    "--role",
    type=click.Choice(ROLE_CHOICES),
    default=AdminRole.SUPER_ADMIN.value,
    show_default=True,
    help="Staff role to grant.",
)
@click.option("--username", default=None, help="Defaults to one derived from email.")
@click.option(
    "--promote",
    is_flag=True,
    help="Grant the role to an existing account instead of refusing.",
)
@click.option(
    "--password",
    envvar="MARKT_ADMIN_PASSWORD",
    default=None,
    help="Prompted for (hidden) when omitted; or set MARKT_ADMIN_PASSWORD.",
)
@with_appcontext
def create_admin(email, role, username, promote, password):
    """Create a staff account for the admin console, or promote one."""
    with session_scope() as session:
        exists = session.query(User.id).filter(User.email == email.strip().lower())
        if not password and not (promote and exists.first()):
            password = click.prompt(
                "Password", hide_input=True, confirmation_prompt=True
            )
        try:
            user, created = provision_admin(
                session,
                email=email,
                role=role,
                password=password,
                username=username,
                promote=promote,
            )
        except AdminProvisionError as e:
            raise click.ClickException(str(e)) from e
        user_id, user_email, user_name = user.id, user.email, user.username

    verb = "Created" if created else "Promoted"
    click.echo(f"{verb} {role} {user_email} (id {user_id}, username {user_name}).")
