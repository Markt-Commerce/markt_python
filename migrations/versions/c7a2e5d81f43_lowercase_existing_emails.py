"""lowercase existing emails

`users.email` is unique over the string, so "Ada@example.com" and
"ada@example.com" were two different rows and the duplicate check on register
never fired. The schema layer now lowercases on the way in; this brings the
rows that were written before it already existed into line.

Deliberately does NOT touch a row whose lowercased form collides with another
account. Merging two accounts means deciding which orders, shop and wallet
survive -- that is a product decision with real money attached, not something
a schema migration gets to make silently. Those rows keep their original
casing and are printed so they can be dealt with by hand; they are the only
ones that stay broken, and they can still sign in exactly as before.

Revision ID: c7a2e5d81f43
Revises: b3e7a91c52d4
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa


revision = "c7a2e5d81f43"
down_revision = "b3e7a91c52d4"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    colliding = conn.execute(
        sa.text(
            """
            SELECT lower(email) AS key, count(*) AS n
            FROM users
            GROUP BY lower(email)
            HAVING count(*) > 1
            """
        )
    ).fetchall()

    for row in colliding:
        print(
            f"  ! {row.n} accounts share the address {row.key} -- left as they "
            "are, merge them by hand"
        )

    result = conn.execute(
        sa.text(
            """
            UPDATE users
            SET email = lower(email)
            WHERE email <> lower(email)
              AND lower(email) NOT IN (
                  SELECT lower(email) FROM users
                  GROUP BY lower(email) HAVING count(*) > 1
              )
            """
        )
    )
    print(f"  lowercased {result.rowcount} email address(es)")


def downgrade():
    # Casing is not recoverable, and restoring it would reopen the duplicate.
    pass
