"""Analytics records owned by the messenger attribution feature."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Table,
    Uuid,
)
from sqlalchemy.dialects.postgresql import insert

from ugc_bot.infrastructure.db.base import Base

OFFER_CHANNELS = Table(
    "offer_channel_attribution",
    Base.metadata,
    Column("order_id", Uuid(), primary_key=True),
    Column("blogger_id", Uuid(), primary_key=True),
    Column("telegram_sent_at", DateTime(timezone=True)),
    Column("max_sent_at", DateTime(timezone=True)),
    Column("response_channel", String(8)),
    Column("response_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ("order_id", "blogger_id"),
        ("offer_dispatches.order_id", "offer_dispatches.blogger_id"),
        ondelete="CASCADE",
    ),
    CheckConstraint(
        "response_channel IN ('telegram', 'max')",
        name="ck_offer_response_channel",
    ),
)

REGISTRATION_CHANNELS = Table(
    "creator_registration_channels",
    Base.metadata,
    Column(
        "user_id",
        Uuid(),
        ForeignKey("blogger_profiles.user_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("channel", String(8), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    CheckConstraint(
        "channel IN ('telegram', 'max')", name="ck_registration_channel"
    ),
)


def remember_offer_response(order_id, blogger_id, channel, occurred_at):
    return (
        insert(OFFER_CHANNELS)
        .values(
            order_id=order_id,
            blogger_id=blogger_id,
            response_channel=channel.value,
            response_at=occurred_at,
        )
        .on_conflict_do_update(
            index_elements=(
                OFFER_CHANNELS.c.order_id,
                OFFER_CHANNELS.c.blogger_id,
            ),
            set_={
                "response_channel": channel.value,
                "response_at": occurred_at,
            },
            where=OFFER_CHANNELS.c.response_channel.is_(None),
        )
    )
