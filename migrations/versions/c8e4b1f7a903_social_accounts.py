"""feat(users): link verified Google/Apple identities to accounts

Revision ID: c8e4b1f7a903
Revises: 5a14c7d16583
Create Date: 2026-09-06

Additive only. No existing column is altered and no row is touched, so the
password path keeps working exactly as it did.

Keyed on (provider, provider_sub) rather than email: `sub` is the provider's
stable, immutable subject id, while an email can be changed by the user and
Apple's private-relay addresses can be revoked outright. Matching on email
would break the link the moment either happened.

`users.password_hash` is already nullable, so an OAuth-only account needs no
placeholder secret and no schema change here.
"""

from alembic import op
import sqlalchemy as sa

revision = "c8e4b1f7a903"
down_revision = "5a14c7d16583"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "social_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=12), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_sub", sa.String(length=255), nullable=False),
        sa.Column("email_at_link", sa.String(length=255), nullable=True),
        sa.Column("name_at_link", sa.String(length=255), nullable=True),
        sa.Column(
            "email_verified_at_link",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "linked_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # One provider identity can never point at two accounts. This is the
        # constraint that makes "sign in with Google" deterministic.
        sa.UniqueConstraint("provider", "provider_sub", name="uq_social_provider_sub"),
        # And one user holds at most one identity per provider.
        sa.UniqueConstraint("provider", "user_id", name="uq_social_provider_user"),
    )
    op.create_index(
        "ix_social_accounts_user_id", "social_accounts", ["user_id"], unique=False
    )


def downgrade():
    op.drop_index("ix_social_accounts_user_id", table_name="social_accounts")
    op.drop_table("social_accounts")
