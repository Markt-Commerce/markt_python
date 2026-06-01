"""fix(orders): add READY_FOR_DELIVERY to orderstatus enum

Revision ID: a1b2c3d4e5f6
Revises: fef026f03f06
Create Date: 2026-06-02 00:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'fef026f03f06'
branch_labels = None
depends_on = None


def upgrade():
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block in PostgreSQL
    op.execute("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'READY_FOR_DELIVERY'")


def downgrade():
    # PostgreSQL does not support removing an enum value natively.
    # The safest approach is to recreate the enum without the value and cast existing rows.
    op.execute(
        "ALTER TABLE orders ALTER COLUMN status TYPE VARCHAR(50) "
        "USING status::text"
    )
    op.execute("DROP TYPE orderstatus")
    op.execute(
        "CREATE TYPE orderstatus AS ENUM ("
        "'PENDING_PAYMENT', 'PENDING', 'PROCESSING', 'SHIPPED', "
        "'DELIVERED', 'CANCELLED', 'RETURNED', 'FAILED'"
        ")"
    )
    op.execute(
        "ALTER TABLE orders ALTER COLUMN status TYPE orderstatus "
        "USING status::orderstatus"
    )
