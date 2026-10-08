"""join the cart and gamification branches

Revision ID: 5a14c7d16583
Revises: a7d3f1e02c58, e1a7c93b5d20
Create Date: 2026-09-06

Two feature branches were cut from 49bdc993a1eb at the same time and both
merged to develop, so the chain forked:

    49bdc993a1eb --> a7d3f1e02c58  (one cart per buyer)
                 \-> e1a7c93b5d20  (gamification seen + streak)

Alembic then refused to run at all -- "Multiple head revisions are present for
given argument 'head'" -- which took the deploy job down with it, since it
upgrades to `head` and there was no longer a single one.

This joins them. It is structural only: there is no schema change here and
nothing to do in either direction. The two branches touch disjoint tables
(`carts` versus `gam_user_*`), so their order relative to each other never
mattered and joining them cannot lose anything.

Empty upgrade/downgrade bodies are correct for a merge revision -- the work is
in the `down_revision` tuple above, which is what gives the chain one head
again.
"""

from alembic import op
import sqlalchemy as sa

revision = "5a14c7d16583"
down_revision = ("a7d3f1e02c58", "e1a7c93b5d20")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
