"""join the tier-colour and location branches

Revision ID: 17f4cd9b003f
Revises: d5b82f1c04a7, f2c9a7e14b06
Create Date: 2026-09-11

Three branches were cut from the same revision and merged independently, so
the chain forked again:

    c8e4b1f7a903 --> d5b82f1c04a7  (tier colours onto the brand ramp)
                 -> f2c9a7e14b06  (browse locations + seller coord index)

Structural only: no schema change, nothing to do in either direction. The two
touch disjoint tables (`gam_tier_config` versus `browse_locations` / `sellers`),
so their order relative to each other never mattered.

This is the second time this has happened, and the second time is the useful
one: `scripts/check_single_migration_head.py` caught it in the lint job on
develop rather than letting the deploy die on `upgrade head`, which is exactly
what that check was added for. The lesson for next time is to chain parallel
feature branches off each other rather than all off develop.
"""

from alembic import op
import sqlalchemy as sa

revision = "17f4cd9b003f"
down_revision = ("d5b82f1c04a7", "f2c9a7e14b06")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
