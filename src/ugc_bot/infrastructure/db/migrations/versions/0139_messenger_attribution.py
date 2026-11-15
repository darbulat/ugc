"""Record the messenger of offer delivery, response and registration."""

import sqlalchemy as sa
from alembic import op

revision = "0139_messenger_attribution"
down_revision = "0138_invite_handoff"
branch_labels = None
depends_on = None

_COLUMNS = {
    "offer_dispatches": (
        ("telegram_sent_at", sa.DateTime(timezone=True)),
        ("max_sent_at", sa.DateTime(timezone=True)),
        ("response_channel", sa.String(8)),
        ("response_at", sa.DateTime(timezone=True)),
    ),
    "instagram_verification_codes": (("request_channel", sa.String(8)),),
    "blogger_profiles": (
        ("registration_channel", sa.String(8)),
        ("registration_completed_at", sa.DateTime(timezone=True)),
    ),
}


def upgrade() -> None:
    for table, columns in _COLUMNS.items():
        for name, column_type in columns:
            op.add_column(table, sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for table, columns in reversed(tuple(_COLUMNS.items())):
        for name, _ in reversed(columns):
            op.drop_column(table, name)
