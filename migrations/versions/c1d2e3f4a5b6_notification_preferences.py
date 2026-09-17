"""add explicit marketing consent to notification preferences

Also adds the seven new notificationtype labels the Python enum grew, since
notifications.type is a native Postgres enum -- without them every chat and
wallet notification would fail at insert, and silently, because each caller
wraps its own notification in try/except.

Chained after the delivery-partner-wallet migration rather than beside it:
both were written against f3a81c62d907, which left two heads and would have
stopped `flask db upgrade` dead on deploy.
"""

from alembic import op
import sqlalchemy as sa


revision = "c1d2e3f4a5b6"
down_revision = "a4f8c2e91d67"
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
        "user_settings",
        "marketing_notifications",
        nullable=False,
        server_default=sa.false(),
    )
    for label in (
        "CHAT_MESSAGE",
        "CHAT_OFFER",
        "CHAT_OFFER_RESPONSE",
        "WALLET_TOPUP_COMPLETED",
        "WALLET_TOPUP_FAILED",
        "WITHDRAWAL_COMPLETED",
        "WITHDRAWAL_FAILED",
    ):
        op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{label}'")


def downgrade():
    op.drop_column("user_settings", "marketing_notifications")
