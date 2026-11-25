"""feat(users): add seller verification_documents

Stores the documents submitted with a seller application (gov ID, proof of
address/registration, shop photos) as JSON, referencing uploaded media. Backs
the non-auto-activating application flow
(AccountService.submit_seller_application) and the admin review surface.

Revision ID: a1c7e9d2b4f0
Revises: e9f4a1b2c3d4
Create Date: 2026-11-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1c7e9d2b4f0"
down_revision = "e9f4a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sellers", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("verification_documents", sa.JSON(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("sellers", schema=None) as batch_op:
        batch_op.drop_column("verification_documents")
