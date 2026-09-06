"""fix(cart): merge duplicate carts and enforce one per buyer

Revision ID: a7d3f1e02c58
Revises: 49bdc993a1eb
Create Date: 2026-09-05

Buyers accumulated cart rows. `Cart.expires_at` defaulted to
`datetime.utcnow() + timedelta(days=30)` -- an expression, so SQLAlchemy
stored the result as a scalar default computed once at import. Every cart a
process created got the same timestamp, and after that moment passed, new
carts were born expired. The read path filters on `expires_at > now()`, so an
expired cart is invisible and the next add-to-cart made another one.

Combined with a `.first()` that had no ordering, checkout could clear one cart
while the app kept reading a different one -- a paid-for item stayed in the
basket. On the local database this left one buyer with three carts, two of
them still holding items.

This migration:
  1. merges each buyer's cart items into their newest cart (summing
     quantities where the same product/variant appears in both),
  2. deletes the emptied duplicates,
  3. refreshes expiries that are already in the past, so no live cart is
     invisible on deploy,
  4. adds a unique constraint on buyer_id so it cannot recur.

Idempotent: re-running finds no duplicates and no past expiries.
"""

from alembic import op
import sqlalchemy as sa

revision = "a7d3f1e02c58"
down_revision = "49bdc993a1eb"
branch_labels = None
depends_on = None

CART_TTL_DAYS = 30


def upgrade():
    conn = op.get_bind()

    # 1. Move items onto the surviving (newest) cart. Where the same
    #    product/variant is in both, add the quantities rather than trip the
    #    cart_items uniqueness and lose one.
    conn.execute(
        sa.text(
            """
            WITH keep AS (
                SELECT buyer_id, MAX(id) AS cart_id
                FROM carts
                GROUP BY buyer_id
            ),
            dupes AS (
                SELECT c.id AS old_cart_id, k.cart_id AS new_cart_id
                FROM carts c
                JOIN keep k ON k.buyer_id = c.buyer_id
                WHERE c.id <> k.cart_id
            )
            UPDATE cart_items ci
            SET quantity = ci.quantity + src.quantity
            FROM cart_items src
            JOIN dupes d ON d.old_cart_id = src.cart_id
            WHERE ci.cart_id = d.new_cart_id
              AND ci.product_id = src.product_id
              AND ci.variant_id IS NOT DISTINCT FROM src.variant_id
            """
        )
    )

    conn.execute(
        sa.text(
            """
            WITH keep AS (
                SELECT buyer_id, MAX(id) AS cart_id
                FROM carts
                GROUP BY buyer_id
            ),
            dupes AS (
                SELECT c.id AS old_cart_id, k.cart_id AS new_cart_id
                FROM carts c
                JOIN keep k ON k.buyer_id = c.buyer_id
                WHERE c.id <> k.cart_id
            )
            UPDATE cart_items ci
            SET cart_id = d.new_cart_id
            FROM dupes d
            WHERE ci.cart_id = d.old_cart_id
              AND NOT EXISTS (
                  SELECT 1 FROM cart_items existing
                  WHERE existing.cart_id = d.new_cart_id
                    AND existing.product_id = ci.product_id
                    AND existing.variant_id IS NOT DISTINCT FROM ci.variant_id
              )
            """
        )
    )

    # Anything left on a duplicate cart was merged by the first statement.
    conn.execute(
        sa.text(
            """
            DELETE FROM cart_items ci
            USING carts c
            WHERE ci.cart_id = c.id
              AND c.id <> (SELECT MAX(id) FROM carts WHERE buyer_id = c.buyer_id)
            """
        )
    )

    # 2. Drop the now-empty duplicates.
    conn.execute(
        sa.text(
            """
            DELETE FROM carts c
            WHERE c.id <> (SELECT MAX(id) FROM carts WHERE buyer_id = c.buyer_id)
            """
        )
    )

    # 3. No surviving cart should already be expired -- that is the state that
    #    made carts invisible in the first place.
    conn.execute(
        sa.text(
            f"""
            UPDATE carts
            SET expires_at = NOW() + INTERVAL '{CART_TTL_DAYS} days'
            WHERE expires_at IS NULL OR expires_at <= NOW()
            """
        )
    )

    # 4. Make the duplicate state unrepresentable.
    op.create_unique_constraint("uq_carts_buyer_id", "carts", ["buyer_id"])


def downgrade():
    # Only the constraint is reversible. The merged carts are not restored:
    # the duplicates were a bug, and re-splitting them would mean inventing an
    # allocation of items across carts that no longer exists.
    op.drop_constraint("uq_carts_buyer_id", "carts", type_="unique")
