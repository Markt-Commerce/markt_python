"""fix(gamification): move tier colours onto the brand ramp

Revision ID: d5b82f1c04a7
Revises: c8e4b1f7a903
Create Date: 2026-09-10

`gam_tier_config.color_hex` held six unrelated hues -- slate, sienna, grey,
orange, teal, and #3A86FF, a vivid blue -- chosen without reference to the
palette. Because they live in the database they bypassed the app's design
tokens entirely and were invisible to its colour linter, which is how a blue
accent came to render inside an orange app.

Replaced with one ascending ramp inside the brand family. The app now derives a
theme-aware colour from the tier *key* rather than reading these, so a badge is
correct in both light and dark; these values remain the fallback for other
consumers (email, a future web client) and for older app builds.

Only rows still holding a known legacy value are touched, so a colour someone
has deliberately changed since is left alone.
"""

from alembic import op
import sqlalchemy as sa

revision = "d5b82f1c04a7"
down_revision = "c8e4b1f7a903"
branch_labels = None
depends_on = None

# tier -> (new, the legacy value we are replacing)
RAMP = {
    "newcomer": ("#6B6B75", "#5C677D"),
    "hustler": ("#F4A98F", "#A0522D"),
    "trader": ("#F4805F", "#9AA0A6"),
    "merchant": ("#E94C2A", "#E36414"),
    "magnate": ("#C93E1F", "#0F4C5C"),
    "mogul": ("#9E3B22", "#3A86FF"),
}


def upgrade():
    conn = op.get_bind()
    for tier, (new, old) in RAMP.items():
        conn.execute(
            sa.text(
                "UPDATE gam_tier_config SET color_hex = :new "
                "WHERE tier = :tier AND color_hex = :old"
            ),
            {"new": new, "tier": tier, "old": old},
        )


def downgrade():
    conn = op.get_bind()
    for tier, (new, old) in RAMP.items():
        conn.execute(
            sa.text(
                "UPDATE gam_tier_config SET color_hex = :old "
                "WHERE tier = :tier AND color_hex = :new"
            ),
            {"new": new, "tier": tier, "old": old},
        )
