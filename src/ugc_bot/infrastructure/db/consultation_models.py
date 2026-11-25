"""Optional consultation reservations, isolated from creator entitlements."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.domain.order_intake import CONSULTATION_MINOR
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.browser_checkout_models import checkout_attempts

CONSULTATIONS = sa.Table(
    "order_consultations",
    Base.metadata,
    sa.Column(
        "order_id",
        sa.Uuid(),
        sa.ForeignKey("orders.order_id"),
        primary_key=True,
    ),
    sa.Column("client_id", sa.Uuid(), nullable=False),
    sa.Column("token", sa.Uuid(), nullable=False, unique=True),
)

CONSULTATION_ATTEMPTS = checkout_attempts(
    "consultation_checkout",
    "order_consultations.order_id",
    f"amount_minor = {CONSULTATION_MINOR}",
    reserved_states="state IN ('creating', 'pending', 'review', 'paid')",
)


async def consultation_tables_installed(db: AsyncSession) -> bool:
    return bool(
        await db.scalar(
            sa.text(
                "SELECT to_regclass('order_consultations') IS NOT NULL "
                "AND to_regclass('consultation_checkout_attempts') IS NOT NULL"
            )
        )
    )


def consultation_status(order_id):
    latest = (
        sa.select(CONSULTATION_ATTEMPTS.c.state)
        .where(CONSULTATION_ATTEMPTS.c.order_id == order_id)
        .order_by(CONSULTATION_ATTEMPTS.c.created_at.desc())
        .limit(1)
        .scalar_subquery()
        .correlate(CONSULTATIONS)
    )
    return sa.func.coalesce(latest, "available")
