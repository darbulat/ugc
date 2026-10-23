"""Real Postgres: an existing legacy balance cannot escape a dispute."""

import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot.domain.entities import Interaction, PayoutRequest
from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    OrderStatus,
    PayoutRequestStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    OrderModel,
    PayoutRequestModel,
    ReferralIncomeEntryModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.interactions import (
    SqlAlchemyInteractionRepository,
)
from ugc_bot.infrastructure.db.repositories.referrals import (
    SqlAlchemyPayoutRequestRepository,
)


@pytest_asyncio.fixture
async def guard_session_factory():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("Requires an explicitly isolated financial PostgreSQL")
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost", "db_test"} or not (
        parsed.database and parsed.database.endswith("_test")
    ):
        pytest.fail("Refusing an unapproved financial test database")
    if parsed.query or parsed.drivername != "postgresql+psycopg":
        pytest.fail("Refusing non-canonical connection parameters")
    # Only this freshly generated database is migrated/dropped; the supplied
    # test database is an admin connection, never a cleanup target.
    import asyncio
    import sys
    from pathlib import Path

    database = "guard_" + uuid4().hex + "_test"
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
    own_url = parsed.set(database=database).render_as_string(
        hide_password=False
    )
    engine = create_async_engine(own_url)
    try:
        env = dict(os.environ, DATABASE_URL=own_url)
        env.pop("MIGRATION_SCHEMA", None)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        assert process.returncode == 0, output.decode()
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.exec_driver_sql(f'DROP DATABASE "{database}"')
        await admin.dispose()


async def seed_available_income(factory, *, recipient=None, currency="RUB"):
    recipient, creator, advertiser, order_id = (uuid4() for _ in range(4))
    async with factory.begin() as session:
        for user_id in [recipient, creator, advertiser]:
            session.add(
                UserModel(
                    user_id=user_id,
                    username="synthetic_financial_test",
                    messenger_type=MessengerType.TELEGRAM,
                    status=UserStatus.ACTIVE,
                )
            )
        await session.flush()
        session.add(
            OrderModel(
                order_id=order_id,
                advertiser_id=advertiser,
                product_link="https://example.invalid/product",
                offer_text="Synthetic test",
                price=500,
                bloggers_needed=1,
                status=OrderStatus.CLOSED,
                currency=currency,
            )
        )
        session.add(
            UserReferralBindingModel(
                referrer_user_id=recipient, referred_user_id=creator
            )
        )
        await session.flush()
        session.add(
            ReferralIncomeEntryModel(
                entry_id=uuid4(),
                referrer_user_id=recipient,
                referred_user_id=creator,
                order_id=order_id,
                income_type="creator",
                currency=currency,
                platform_revenue=Decimal("500"),
                commission_rate=Decimal("0.1"),
                commission_amount=Decimal("50"),
            )
        )
    now = datetime.now(timezone.utc)
    interaction = Interaction(
        interaction_id=uuid4(),
        order_id=order_id,
        blogger_id=creator,
        advertiser_id=advertiser,
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=None,
        created_at=now,
        updated_at=now,
    )
    return recipient, interaction


@pytest.mark.asyncio
async def test_issue_blocks_existing_available_income(guard_session_factory):
    from dataclasses import replace

    factory = guard_session_factory
    recipient, interaction = await seed_available_income(factory)
    payouts = SqlAlchemyPayoutRequestRepository(factory)
    interactions = SqlAlchemyInteractionRepository(factory)
    request = PayoutRequest(
        request_id=uuid4(),
        user_id=recipient,
        requested_at=datetime.now(timezone.utc),
        status=PayoutRequestStatus.PENDING,
        amount=Decimal("50"),
        currency="RUB",
    )
    await interactions.save(interaction)
    await payouts.save(request)
    await interactions.save(
        replace(
            interaction,
            status=InteractionStatus.ISSUE,
            from_blogger="⚠️ Проблема",
        )
    )
    with pytest.raises(ValueError, match="dispute"):
        await payouts.update_status(
            request.request_id, PayoutRequestStatus.PAID
        )
    async with factory() as session:
        stored = await session.scalar(
            select(PayoutRequestModel).where(
                PayoutRequestModel.request_id == request.request_id
            )
        )
        assert stored.status == PayoutRequestStatus.PENDING


@pytest.mark.asyncio
async def test_issue_prevents_creating_another_request(guard_session_factory):
    from dataclasses import replace

    factory = guard_session_factory
    recipient, interaction = await seed_available_income(factory)
    await SqlAlchemyInteractionRepository(factory).save(
        replace(interaction, status=InteractionStatus.ISSUE)
    )
    request = PayoutRequest(
        request_id=uuid4(),
        user_id=recipient,
        requested_at=datetime.now(timezone.utc),
        status=PayoutRequestStatus.PENDING,
        amount=Decimal("50"),
        currency="RUB",
    )
    with pytest.raises(ValueError, match="dispute"):
        await SqlAlchemyPayoutRequestRepository(factory).save(request)


@pytest.mark.asyncio
async def test_concurrent_feedback_keeps_both_sides_and_dispute(
    guard_session_factory,
):
    import asyncio

    from ugc_bot.application.services.interaction_service import (
        InteractionService,
    )
    from ugc_bot.infrastructure.db.session import SessionTransactionManager

    factory = guard_session_factory
    _, interaction = await seed_available_income(factory)
    barrier = asyncio.Barrier(2)
    armed = True

    class RacingReadRepository(SqlAlchemyInteractionRepository):
        async def get_by_id(self, interaction_id, session=None):
            result = await super().get_by_id(interaction_id, session=session)
            if armed:
                await barrier.wait()
            return result

    repo = RacingReadRepository(factory)
    await repo.save(interaction)
    service = InteractionService(
        interaction_repo=repo,
        transaction_manager=SessionTransactionManager(factory),
    )
    await asyncio.gather(
        service.record_advertiser_feedback(
            interaction.interaction_id, "✅ Сделка состоялась"
        ),
        service.record_blogger_feedback(
            interaction.interaction_id, "❌ Не договорились"
        ),
    )
    armed = False
    stored = await repo.get_by_id(interaction.interaction_id)
    assert stored.from_advertiser is not None
    assert stored.from_blogger is not None
    assert stored.status == InteractionStatus.ISSUE


@pytest.mark.asyncio
async def test_unrelated_currency_is_not_frozen(guard_session_factory):
    from dataclasses import replace

    factory = guard_session_factory
    recipient, disputed = await seed_available_income(factory)
    await seed_available_income(factory, recipient=recipient, currency="USD")
    await SqlAlchemyInteractionRepository(factory).save(
        replace(disputed, status=InteractionStatus.ISSUE)
    )
    request = PayoutRequest(
        request_id=uuid4(),
        user_id=recipient,
        requested_at=datetime.now(timezone.utc),
        status=PayoutRequestStatus.PENDING,
        amount=Decimal("35"),
        currency="USD",
    )
    repo = SqlAlchemyPayoutRequestRepository(factory)
    await repo.save(request)
    assert await repo.update_status(
        request.request_id, PayoutRequestStatus.PAID
    )
    assert (
        await repo.get_by_id(request.request_id)
    ).status == PayoutRequestStatus.PAID


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "mark_paid"])
async def test_issue_blocks_payout_under_race(guard_session_factory, operation):
    import asyncio
    from dataclasses import replace

    from ugc_bot.application.errors import LegacyPayoutBlockedError
    from ugc_bot.infrastructure.db.session import SessionTransactionManager

    factory = guard_session_factory
    recipient, interaction = await seed_available_income(factory)
    interactions = SqlAlchemyInteractionRepository(factory)
    await interactions.save(interaction)
    payouts = SqlAlchemyPayoutRequestRepository(factory)
    request = PayoutRequest(
        request_id=uuid4(),
        user_id=recipient,
        requested_at=datetime.now(timezone.utc),
        status=PayoutRequestStatus.PENDING,
        amount=Decimal("35"),
        currency="RUB",
    )
    if operation == "mark_paid":
        await payouts.save(request)
    tm = SessionTransactionManager(factory)

    async def pay():
        async with tm.transaction() as session:
            if operation == "create":
                await payouts.save(request, session=session)
                return True
            return await payouts.update_status(
                request.request_id, PayoutRequestStatus.PAID, session=session
            )

    async with tm.transaction() as session:
        await interactions.save(
            replace(interaction, status=InteractionStatus.ISSUE),
            session=session,
        )
        task = asyncio.create_task(pay())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(task), 0.2)
    with pytest.raises(LegacyPayoutBlockedError):
        await task
    stored = await payouts.get_by_id(request.request_id)
    if operation == "create":
        assert stored is None
    else:
        assert stored.status == PayoutRequestStatus.PENDING


@pytest.mark.asyncio
async def test_issue_rollback_does_not_leave_phantom_block(
    guard_session_factory,
):
    from dataclasses import replace

    from ugc_bot.infrastructure.db.session import SessionTransactionManager

    factory = guard_session_factory
    recipient, interaction = await seed_available_income(factory)
    interactions = SqlAlchemyInteractionRepository(factory)
    await interactions.save(interaction)
    with pytest.raises(RuntimeError, match="abort synthetic transaction"):
        async with SessionTransactionManager(factory).transaction() as session:
            await interactions.save(
                replace(interaction, status=InteractionStatus.ISSUE),
                session=session,
            )
            raise RuntimeError("abort synthetic transaction")
    request = PayoutRequest(
        request_id=uuid4(),
        user_id=recipient,
        requested_at=datetime.now(timezone.utc),
        status=PayoutRequestStatus.PENDING,
        amount=Decimal("35"),
        currency="RUB",
    )
    repo = SqlAlchemyPayoutRequestRepository(factory)
    await repo.save(request)
    assert await repo.update_status(
        request.request_id, PayoutRequestStatus.PAID
    )


@pytest.mark.asyncio
async def test_downgrade_lock_cannot_lose_a_racing_guard(
    guard_session_factory, monkeypatch
):
    import asyncio
    import importlib.util
    from dataclasses import replace
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.util.concurrency import await_only

    factory = guard_session_factory
    _, interaction = await seed_available_income(factory)
    repo = SqlAlchemyInteractionRepository(factory)
    await repo.save(interaction)
    path = (
        Path(__file__).resolve().parents[2]
        / "src/ugc_bot/infrastructure/db/migrations/versions"
        / "legacy_financial_guard.py"
    )
    spec = importlib.util.spec_from_file_location("guard_downgrade_race", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    checked, allow_drop = asyncio.Event(), asyncio.Event()

    async def downgrade():
        async with factory.kw["bind"].begin() as connection:

            def run(sync_connection):
                class PauseAfterEmptyCheck:
                    def execute(self, statement):
                        result = sync_connection.execute(statement)
                        if "SELECT" in str(
                            statement
                        ) and "legacy_financial_guards" in str(statement):
                            checked.set()
                            await_only(allow_drop.wait())
                        return result

                operations = Operations(
                    MigrationContext.configure(sync_connection)
                )
                monkeypatch.setattr(
                    operations, "get_bind", lambda: PauseAfterEmptyCheck()
                )
                monkeypatch.setattr(migration, "op", operations)
                migration.downgrade()

            await connection.run_sync(run)

    migration_task = asyncio.create_task(downgrade())
    await asyncio.wait_for(checked.wait(), 5)
    issue_task = asyncio.create_task(
        repo.save(replace(interaction, status=InteractionStatus.ISSUE))
    )
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(issue_task), 0.2)
    finally:
        allow_drop.set()
        await migration_task
    # DDL won before the issue could commit: the losing writer fails closed,
    # rather than a committed financial safety-stop silently disappearing.
    result = (await asyncio.gather(issue_task, return_exceptions=True))[0]
    assert isinstance(result, SQLAlchemyError)
    assert (
        await repo.get_by_id(interaction.interaction_id)
    ).status == InteractionStatus.PENDING


@pytest.mark.asyncio
async def test_paid_fact_wins_before_issue_without_rewriting_income(
    guard_session_factory,
):
    import asyncio
    from dataclasses import replace

    from sqlalchemy import select

    from ugc_bot.infrastructure.db.session import SessionTransactionManager

    factory = guard_session_factory
    recipient, interaction = await seed_available_income(factory)
    interactions = SqlAlchemyInteractionRepository(factory)
    await interactions.save(interaction)
    payouts = SqlAlchemyPayoutRequestRepository(factory)
    request = PayoutRequest(
        request_id=uuid4(),
        user_id=recipient,
        requested_at=datetime.now(timezone.utc),
        status=PayoutRequestStatus.PENDING,
        amount=Decimal("35"),
        currency="RUB",
    )
    await payouts.save(request)
    columns = select(
        ReferralIncomeEntryModel.entry_id,
        ReferralIncomeEntryModel.commission_amount,
        ReferralIncomeEntryModel.commission_rate,
        ReferralIncomeEntryModel.platform_revenue,
    )
    async with factory() as session:
        before = (await session.execute(columns)).all()
    async with SessionTransactionManager(factory).transaction() as session:
        assert await payouts.update_status(
            request.request_id, PayoutRequestStatus.PAID, session=session
        )
        issue = asyncio.create_task(
            interactions.save(
                replace(interaction, status=InteractionStatus.ISSUE)
            )
        )
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(issue), 0.2)
    await issue
    paid = await payouts.get_by_id(request.request_id)
    assert paid.status == PayoutRequestStatus.PAID
    assert paid.amount == Decimal("35")
    async with factory() as session:
        assert (await session.execute(columns)).all() == before
    assert (
        await interactions.get_by_id(interaction.interaction_id)
    ).status == InteractionStatus.ISSUE


@pytest.mark.asyncio
async def test_downgrade_rejects_committed_guard_without_dropping_history(
    guard_session_factory, monkeypatch
):
    import importlib.util
    from dataclasses import replace
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    factory = guard_session_factory
    _, interaction = await seed_available_income(factory)
    await SqlAlchemyInteractionRepository(factory).save(
        replace(interaction, status=InteractionStatus.ISSUE)
    )
    path = (
        Path(__file__).resolve().parents[2]
        / "src/ugc_bot/infrastructure/db/migrations/versions"
        / "legacy_financial_guard.py"
    )
    spec = importlib.util.spec_from_file_location(
        "guard_downgrade_active", path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with pytest.raises(RuntimeError, match="Cannot remove"):
        async with factory.kw["bind"].begin() as connection:

            def run(sync_connection):
                monkeypatch.setattr(
                    migration,
                    "op",
                    Operations(MigrationContext.configure(sync_connection)),
                )
                migration.downgrade()

            await connection.run_sync(run)
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM legacy_financial_guards")
            )
            == 1
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM referral_income_entries")
            )
            == 1
        )
