"""Record the messenger of offer delivery, response and registration."""

import sqlalchemy as sa
from alembic import op

revision = "0139_messenger_attribution"
down_revision = "0138_invite_handoff"
branch_labels = None
depends_on = None

_FINISH = """
CREATE FUNCTION finish_creator_channel_registration() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE creator_registration_channels
    SET completed_at = NEW.agreement_confirmed_at
    WHERE user_id = NEW.user_id AND completed_at IS NULL;
    RETURN NEW;
END;
$$;
"""

_TRIGGER = """
CREATE TRIGGER finish_creator_channel_registration
AFTER UPDATE OF agreement_confirmed_at, confirmed ON blogger_profiles
FOR EACH ROW
WHEN (
    NEW.confirmed AND NEW.agreement_confirmed_at IS NOT NULL
    AND (NOT OLD.confirmed OR OLD.agreement_confirmed_at IS NULL)
)
EXECUTE FUNCTION finish_creator_channel_registration();
"""


def upgrade() -> None:
    op.create_table(
        "offer_channel_attribution",
        sa.Column("order_id", sa.Uuid(), primary_key=True),
        sa.Column("blogger_id", sa.Uuid(), primary_key=True),
        sa.Column("telegram_sent_at", sa.DateTime(timezone=True)),
        sa.Column("max_sent_at", sa.DateTime(timezone=True)),
        sa.Column("response_channel", sa.String(8)),
        sa.Column("response_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["order_id", "blogger_id"],
            ["offer_dispatches.order_id", "offer_dispatches.blogger_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "response_channel IN ('telegram', 'max')",
            name="ck_offer_response_channel",
        ),
    )
    op.create_table(
        "creator_registration_channels",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("blogger_profiles.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("channel", sa.String(8), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "channel IN ('telegram', 'max')", name="ck_registration_channel"
        ),
    )
    op.execute(_FINISH)
    op.execute(_TRIGGER)
    op.add_column(
        "instagram_verification_codes",
        sa.Column("request_channel", sa.String(8)),
    )


def downgrade() -> None:
    op.drop_column("instagram_verification_codes", "request_channel")
    op.execute(
        "DROP TRIGGER finish_creator_channel_registration ON blogger_profiles"
    )
    op.execute("DROP FUNCTION finish_creator_channel_registration()")
    op.drop_table("creator_registration_channels")
    op.drop_table("offer_channel_attribution")
