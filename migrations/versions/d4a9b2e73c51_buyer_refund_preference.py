"""where a buyer wants money owed back to land

Only the saving from a shared delivery uses this today. Defaults to 'card' for
everyone, existing rows included: ADR-002 allows wallet credit only as an
opt-in with the cash refund as default, so nobody's refund destination changes
because this shipped.

A plain VARCHAR with a CHECK rather than a native enum. Adding a third
destination later is then a deploy rather than an ALTER TYPE, which needs
ownership of the type -- the thing that currently blocks migrating the local
database at all.

Revision ID: d4a9b2e73c51
Revises: c182c673b6c4
Create Date: 2026-09-12
"""

from alembic import op
import sqlalchemy as sa


revision = "d4a9b2e73c51"
down_revision = "c182c673b6c4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "buyers",
        sa.Column(
            "refund_preference",
            sa.String(length=10),
            nullable=False,
            server_default="card",
        ),
    )
    op.create_check_constraint(
        "ck_buyers_refund_preference",
        "buyers",
        "refund_preference IN ('card', 'wallet')",
    )
    # The server_default existed to fill existing rows without a table
    # rewrite. The model supplies the default from here on, so it does not
    # need to linger in the schema.
    op.alter_column("buyers", "refund_preference", server_default=None)


def downgrade():
    op.drop_constraint("ck_buyers_refund_preference", "buyers", type_="check")
    op.drop_column("buyers", "refund_preference")
