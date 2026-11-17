"""Admin query tuning and narrow matching reads preserve stored facts."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from ugc_bot.admin.app import _configure_admin_query_planning
from ugc_bot.domain.entities import InstagramAudienceCounts
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.models import InstagramStatsModel, UserModel
from ugc_bot.infrastructure.db.repositories.instagram import (
    SqlAlchemyInstagramStatsRepository,
)


def test_admin_jit_setting_expires_at_transaction_end(financial_pg_engine):
    engine = create_engine(financial_pg_engine.url)
    try:
        with engine.connect() as db:
            baseline = db.scalar(text("SHOW jit"))
        _configure_admin_query_planning(engine)
        for _ in range(2):
            with engine.begin() as db:
                assert db.scalar(text("SHOW jit")) == "off"
            raw = engine.raw_connection()
            try:
                with raw.cursor() as cursor:
                    cursor.execute("SHOW jit")
                    assert cursor.fetchone()[0] == baseline
                raw.rollback()
            finally:
                raw.close()
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_matching_counts_preserve_nulls_and_skip_raw_response(
    financial_pg_engine,
):
    first, unknown, absent = (uuid4() for _ in range(3))
    raw_response = {"posts": ["synthetic-response" * 2000]}
    with Session(financial_pg_engine) as db, db.begin():
        db.add_all(
            UserModel(
                user_id=uid,
                username="performance-test",
                messenger_type=MessengerType.TELEGRAM,
                status=UserStatus.ACTIVE,
            )
            for uid in (first, unknown)
        )
        db.flush()
        db.add_all(
            InstagramStatsModel(
                user_id=uid,
                raw_response=raw_response,
                fetched_at=datetime.now(timezone.utc),
                followers_count=followers,
                media_count=media,
            )
            for uid, followers, media in (
                (first, 0, 100),
                (unknown, None, None),
            )
        )
    engine = create_async_engine(financial_pg_engine.url)
    queries = []
    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: queries.append(
            statement
        ),
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyInstagramStatsRepository(sessions)
    try:
        assert await repository.get_audience_counts([]) == {}
        assert queries == []
        counts = await repository.get_audience_counts([first, unknown, absent])
        assert counts == {
            first: InstagramAudienceCounts(0, 100),
            unknown: InstagramAudienceCounts(None, None),
        }
        assert len(queries) == 1 and "raw_response" not in queries[0]
        stats = await repository.get_by_user_ids([first])
        assert stats[first].raw_response == raw_response
        _configure_admin_query_planning(engine.sync_engine)
        async with AsyncSession(engine) as db:
            assert await db.scalar(text("SHOW jit")) == "off"
    finally:
        await engine.dispose()
