"""add explicit marketing consent to notification preferences"""

from alembic import op
import sqlalchemy as sa


revision = "c1d2e3f4a5b6"
down_revision = "f3a81c62d907"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_settings",
        sa.Column("marketing_notifications", sa.Boolean(), nullable=True),
    )
    op.execute(
        "UPDATE user_settings SET marketing_notifications = false "
        "WHERE marketing_notifications IS NULL"
    )
    op.alter_column(
        "user_settings", "marketing_notifications", nullable=False, server_default=sa.false()
    )
    for label in (
        "CHAT_MESSAGE", "CHAT_OFFER", "CHAT_OFFER_RESPONSE",
        "WALLET_TOPUP_COMPLETED", "WALLET_TOPUP_FAILED",
        "WITHDRAWAL_COMPLETED", "WITHDRAWAL_FAILED",
    ):
        op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{label}'")


def downgrade():
    op.drop_column("user_settings", "marketing_notifications")
