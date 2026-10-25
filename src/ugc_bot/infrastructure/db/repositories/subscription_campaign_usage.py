"""Subscription usage comes from actual campaign and delivery facts."""

from sqlalchemy import func, select

from ugc_bot.infrastructure.db.campaign_runtime_models import (
    ATTEMPTS,
    JOBS,
    SUBMISSIONS,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemySubscriptionCampaignUsage:
    async def usage(self, owner_id, starts_at, *, session):
        db = _session(session)
        submissions = await db.scalar(
            select(func.count())
            .select_from(SUBMISSIONS)
            .where(
                SUBMISSIONS.c.owner_id == owner_id,
                SUBMISSIONS.c.recorded_at >= starts_at,
            )
        )
        attempts = await db.scalar(
            select(func.count())
            .select_from(
                ATTEMPTS.join(JOBS, ATTEMPTS.c.job_id == JOBS.c.job_id).join(
                    SUBMISSIONS,
                    JOBS.c.submission_id == SUBMISSIONS.c.submission_id,
                )
            )
            .where(
                SUBMISSIONS.c.owner_id == owner_id,
                ATTEMPTS.c.recorded_at >= starts_at,
            )
        )
        return int(submissions or 0), int(attempts or 0)
