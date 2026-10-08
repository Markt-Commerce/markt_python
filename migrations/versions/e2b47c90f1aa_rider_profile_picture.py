"""A rider can have a face.

Buyers and sellers have had `User.profile_picture` since the beginning.
Riders live in `delivery_users` and simply never got the column -- so the
one person who turns up at a stranger's door was the one with no photo in
the app.

`media` gains `delivery_user_id` for the same reason notifications, push
tokens and wallets did: `media.user_id` is a foreign key to `users`, and a
rider's DEL_ id cannot go in it. Same second-column-plus-XOR shape.

Revision ID: e2b47c90f1aa
Revises: c7f31a90b4de
Create Date: 2026-09-19

"""

import sqlalchemy as sa
from alembic import op

revision = "e2b47c90f1aa"
down_revision = "c7f31a90b4de"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "delivery_users",
        sa.Column("profile_picture", sa.String(length=255), nullable=True),
    )

    op.add_column(
        "media",
        sa.Column("delivery_user_id", sa.String(length=12), nullable=True),
    )
    op.create_index("ix_media_delivery_user_id", "media", ["delivery_user_id"])
    op.create_foreign_key(
        "fk_media_delivery_user_id",
        "media",
        "delivery_users",
        ["delivery_user_id"],
        ["id"],
    )
    # Existing rows all belong to a User, so the XOR holds for them
    # already; it is added after the backfill would have run for that
    # reason.
    op.create_check_constraint(
        "ck_media_single_owner",
        "media",
        "(user_id IS NULL) <> (delivery_user_id IS NULL)",
    )


def downgrade():
    op.drop_constraint("ck_media_single_owner", "media", type_="check")
    op.drop_constraint("fk_media_delivery_user_id", "media", type_="foreignkey")
    op.drop_index("ix_media_delivery_user_id", table_name="media")
    op.drop_column("media", "delivery_user_id")
    op.drop_column("delivery_users", "profile_picture")
