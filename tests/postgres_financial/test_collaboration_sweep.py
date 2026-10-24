"""Production sweep factory drives SQL state, immutable schedule and outbox."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from tests.postgres_financial.test_collaboration_persistence import (
    collaboration_pg as collaboration_pg,
)
from tests.postgres_financial.test_collaboration_persistence import (
    command,
    execute,
    start,
)
from ugc_bot.collaboration_scheduler import run_loop
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.collaboration_models import (
    CollaborationModel,
    CollaborationReleaseScheduleModel,
)


@pytest.mark.asyncio
@pytest.mark.usefixtures("collaboration_pg")
async def test_real_sweep_records_final_and_maturity_after_accepted_notice(
    request,
    financial_pg_engine,
):
    pg = request.getfixturevalue("collaboration_pg")
    factory, service, repo, clock, data = pg
    await start(pg)
    await execute(
        factory,
        service,
        command(data, "claim", "creator", 2, evidence="synthetic proof"),
    )
    async with factory() as db:
        from ugc_bot.infrastructure.db.collaboration_models import (
            CollaborationNoticeModel,
        )

        notice_id = await db.scalar(
            select(CollaborationNoticeModel.notice_id).where(
                CollaborationNoticeModel.assignment_id == data["assignment"]
            )
        )
    await execute(
        factory,
        service,
        command(
            data,
            "notice",
            None,
            3,
            notice_id=notice_id,
            system_actor="collaboration_notifier",
            accepted=True,
            channel="telegram",
            external_reference="synthetic-transport-receipt",
        ),
    )
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": financial_pg_engine.url.render_as_string(
                hide_password=False
            ),
        }
    )
    container = Container(config)
    sweep = container.build_collaboration_sweep()
    # Only time is controlled; SQL, transactions and the loop are real.
    sweep.lifecycle.clock = clock
    try:
        clock.at += timedelta(hours=72)
        await run_loop(sweep, max_iterations=1)
        async with factory() as db:
            row = await db.get(CollaborationModel, data["assignment"])
            assert row.state == "success_final"
            release = await db.scalar(
                select(CollaborationReleaseScheduleModel.release_at).where(
                    CollaborationReleaseScheduleModel.assignment_id
                    == data["assignment"]
                )
            )
            assert release == clock.at + timedelta(days=14)
        clock.at += timedelta(days=14)
        await run_loop(sweep, max_iterations=1)
        async with factory() as db:
            row = await db.get(CollaborationModel, data["assignment"])
            assert row.state == "available"
            assert (
                len(
                    (
                        await db.scalars(
                            select(CollaborationReleaseScheduleModel).where(
                                CollaborationReleaseScheduleModel.assignment_id
                                == data["assignment"]
                            )
                        )
                    ).all()
                )
                == 1
            )
    finally:
        await container.dispose()
