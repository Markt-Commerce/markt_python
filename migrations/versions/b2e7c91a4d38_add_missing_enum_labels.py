"""add enum labels the models grew but the database never got

Revision ID: b2e7c91a4d38
Revises: c4fcdb10ec37
Create Date: 2026-09-04

Three Postgres enum types had fallen behind the Python enums they mirror.
Values were added to the models over time and no migration ever added them to
the database, because **alembic's autogenerate does not diff enum labels** --
`flask db check` reports a clean schema while the type is missing half its
values.

The failure is invisible until someone writes one of the missing values, and
then it's a 500:

    invalid input value for enum order_items_status: "PROCESSING"

Found by driving a real buyer-orders-then-seller-fulfils flow over HTTP. The
seller could see the order and could not act on it at all: PROCESSING is the
only legal first transition out of PENDING, and it did not exist in the
database.

  order_items_status   missing PROCESSING, CANCELLED
                       -> seller fulfilment was completely dead
  notificationtype     missing 8 values, referenced by 42 call sites across
                       fulfilment, delivery, refunds and substitutions
  mediavarianttype     missing the 6 social/responsive variants

Downgrade is a deliberate no-op: PostgreSQL cannot remove a value from an enum
type, and rebuilding all three types to drop labels that should have been there
all along would risk live data to undo a fix.
"""

from alembic import op


revision = "b2e7c91a4d38"
down_revision = "c4fcdb10ec37"
branch_labels = None
depends_on = None


# type name -> labels the model has that the database is missing
MISSING = {
    "order_items_status": ["PROCESSING", "CANCELLED"],
    "notificationtype": [
        "ORDER_CANCELLED",
        "REFUND_ISSUED",
        "ITEM_UNFULFILLED",
        "DELIVERY_FAILED",
        "FULFILMENT_REQUEST",
        "NEW_REQUEST_MATCH",
        "SUBSTITUTION_APPROVAL_REQUIRED",
        "THIN_VOLUME_DELIVERY_CHOICE",
    ],
    "mediavarianttype": [
        "DESKTOP",
        "MOBILE",
        "TABLET",
        "SOCIAL_POST",
        "SOCIAL_SQUARE",
        "SOCIAL_STORY",
    ],
}


def upgrade():
    # IF NOT EXISTS keeps this safe to run against a database that already has
    # some of them -- and safe to re-run.
    #
    # ALTER TYPE ... ADD VALUE is allowed inside a transaction from PostgreSQL
    # 12 onwards provided the new value isn't *used* in the same transaction.
    # This migration only adds; nothing here writes one.
    for type_name, labels in MISSING.items():
        for label in labels:
            op.execute(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{label}'")


def downgrade():
    # PostgreSQL has no ALTER TYPE ... DROP VALUE. Removing these would mean
    # recreating each type and rewriting every column that uses it, to take away
    # values the models legitimately expect. Not worth the risk to reverse a
    # correction.
    pass
