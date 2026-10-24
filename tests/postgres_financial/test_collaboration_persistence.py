"""Genuine migration, scope, rollback and two-session lifecycle proofs."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot.application.collaboration_ports import CollaborationCommand
from ugc_bot.application.services.collaboration_service import (
    CollaborationService,
)
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    OrderStatus,
    PaymentStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    FinancialPolicyVersionModel,
    ItemAssignmentModel,
    ManagerOrderModel,
    OrderItemModel,
    OrderModel,
    OutboxEventModel,
    PaymentItemAllocationModel,
    PaymentModel,
    UserModel,
)


class Clock:
    def __init__(self, at):
        self.at = at

    def now(self):
        return self.at


def test_migration_creates_persisted_lifecycle_tables(financial_pg_engine):
    assert {
        "financial_collaborations",
        "financial_collaboration_events",
        "financial_collaboration_notices",
        "financial_collaboration_schedules",
    } <= set(inspect(financial_pg_engine).get_table_names())


@pytest_asyncio.fixture
async def collaboration_pg(financial_pg_engine, request):
    try:
        from ugc_bot.infrastructure.db.repositories.collaborations import (
            SqlAlchemyCollaborationRepository,
        )
    except ModuleNotFoundError:
        pytest.fail("SQL collaboration command adapter is missing")
    engine = create_async_engine(financial_pg_engine.url, pool_size=5)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 10, 23, tzinfo=timezone.utc)
    client, creator, manager, order, item, assignment, payment = [
        uuid4() for _ in range(7)
    ]
    policy = str(uuid4())
    async with factory.begin() as db:
        db.add_all(
            [
                UserModel(
                    user_id=uid,
                    messenger_type=MessengerType.TELEGRAM,
                    username="synthetic",
                    status=UserStatus.ACTIVE,
                )
                for uid in (client, creator, manager)
            ]
        )
        await db.flush()
        db.add_all(
            [
                AdvertiserProfileModel(user_id=client, contact="synthetic"),
                BloggerProfileModel(
                    user_id=creator,
                    instagram_url=f"https://instagram.com/{creator.hex}",
                    confirmed=True,
                    topics={},
                    audience_gender=AudienceGender.ALL,
                    audience_age_min=18,
                    audience_age_max=65,
                    audience_geo="synthetic",
                    price=1,
                ),
                FinancialPolicyVersionModel(
                    version=policy,
                    approved_by=client,
                    approved_at=now - timedelta(days=2),
                    effective_from=now - timedelta(days=1),
                    refund_window_seconds=3600,
                    rules={},
                ),
                OrderModel(
                    order_id=order,
                    advertiser_id=client,
                    product_link="synthetic",
                    offer_text="synthetic",
                    price=500,
                    bloggers_needed=1,
                    status=OrderStatus.ACTIVE,
                    financial_version=policy,
                ),
            ]
        )
        await db.flush()
        db.add_all(
            [
                OrderItemModel(
                    paid_item_id=item,
                    order_id=order,
                    ordinal=1,
                    currency="RUB",
                    selection_minor=50000,
                    accompaniment_minor=0,
                    policy_version=policy,
                    selection_due_at=now + timedelta(days=2),
                    captured_at=now - timedelta(hours=2),
                    quote_key="synthetic",
                    quote_payload={},
                ),
                PaymentModel(
                    payment_id=payment,
                    order_id=order,
                    provider="synthetic",
                    status=PaymentStatus.PAID,
                    amount=500,
                    captured_minor=50000,
                    financial_version=policy,
                    currency="RUB",
                    external_id=str(payment),
                ),
                ManagerOrderModel(
                    user_id=manager,
                    order_id=order,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await db.flush()
        db.add_all(
            [
                ItemAssignmentModel(
                    assignment_id=assignment,
                    paid_item_id=item,
                    version=1,
                    creator_id=creator,
                    manager_id=manager,
                    valid_from=now - timedelta(hours=1),
                    reason="agreed synthetic assignment",
                    actor_id=client,
                ),
                *(
                    [
                        PaymentItemAllocationModel(
                            allocation_key=str(uuid4()),
                            payment_id=payment,
                            paid_item_id=item,
                            order_id=order,
                            component="selection",
                            amount_minor=50000,
                            currency="RUB",
                        )
                    ]
                    if getattr(request, "param", True)
                    else []
                ),
            ]
        )
    clock = Clock(now)
    repo = SqlAlchemyCollaborationRepository()
    service = CollaborationService(repo, clock)
    data = dict(
        client=client,
        creator=creator,
        manager=manager,
        order=order,
        item=item,
        assignment=assignment,
    )
    yield factory, service, repo, clock, data
    await engine.dispose()


def command(data, action, actor, version, key=None, **extra):
    return CollaborationCommand(
        assignment_id=data["assignment"],
        action=action,
        actor_id=data.get(actor) if actor else None,
        operation_key=key or action,
        expected_version=version,
        **extra,
    )


async def execute(factory, service, cmd):
    async with factory.begin() as db:
        return await service.execute(cmd, session=db)


async def start(pg):
    factory, service, _, clock, data = pg
    await execute(
        factory,
        service,
        command(
            data,
            "assign",
            "client",
            0,
            due_at=clock.at + timedelta(days=2),
            terms_reference="client-consented:1",
        ),
    )
    return await execute(factory, service, command(data, "start", "manager", 1))


@pytest.mark.asyncio
async def test_sql_claim_replay_keeps_one_notice_and_one_event(
    collaboration_pg,
):
    factory, service, repo, clock, data = collaboration_pg
    current = await start(collaboration_pg)
    cmd = command(
        data,
        "claim",
        "creator",
        current.version,
        evidence="https://example.com/proof",
    )
    result = await execute(factory, service, cmd)
    clock.at += timedelta(hours=1)
    assert await execute(factory, service, cmd) == result
    async with factory.begin() as db:
        assert (
            await repo.get(data["assignment"], session=db)
        ).collaboration.claimed_at == datetime(
            2026, 10, 23, tzinfo=timezone.utc
        )
        assert (
            await db.scalar(
                text(
                    "select count(*) from financial_collaboration_notices "
                    "where assignment_id=:id"
                ),
                {"id": data["assignment"]},
            )
            == 1
        )
        assert (
            await db.scalar(
                text(
                    "select count(*) from financial_collaboration_events "
                    "where assignment_id=:id"
                ),
                {"id": data["assignment"]},
            )
            == 3
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.aggregate_id == str(data["assignment"]))
            )
            == 4
        )


@pytest.mark.asyncio
async def test_two_postgres_sessions_serialize_same_expected_version(
    collaboration_pg,
):
    factory, service, _, _, data = collaboration_pg
    await start(collaboration_pg)
    barrier = asyncio.Barrier(2)
    pids = set()

    async def claim(actor):
        async with factory.begin() as db:
            pids.add(await db.scalar(text("select pg_backend_pid()")))
            await barrier.wait()
            return await service.execute(
                command(
                    data,
                    "claim",
                    actor,
                    2,
                    key=f"claim-{actor}",
                    evidence="content",
                ),
                session=db,
            )

    results = await asyncio.gather(
        claim("client"), claim("creator"), return_exceptions=True
    )
    assert len(pids) == 2
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    errors = [result for result in results if isinstance(result, BaseException)]
    assert str(errors[0]) == "collaboration_version_conflict"
    async with factory.begin() as db:
        assert (
            await db.scalar(
                text(
                    "select count(*) from financial_collaboration_notices "
                    "where assignment_id=:id"
                ),
                {"id": data["assignment"]},
            )
            == 1
        )


@pytest.mark.asyncio
async def test_sql_rollback_removes_claim_notice_and_outbox_together(
    collaboration_pg,
):
    factory, service, repo, _, data = collaboration_pg
    await start(collaboration_pg)
    with pytest.raises(RuntimeError, match="abort caller"):
        async with factory.begin() as db:
            await service.execute(
                command(data, "claim", "creator", 2, evidence="proof"),
                session=db,
            )
            raise RuntimeError("abort caller")
    async with factory.begin() as db:
        assert (await repo.get(data["assignment"], session=db)).version == 2
        assert (
            await db.scalar(
                text(
                    "select count(*) from financial_collaboration_notices "
                    "where assignment_id=:id"
                ),
                {"id": data["assignment"]},
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.aggregate_id == str(data["assignment"]))
            )
            == 2
        )


@pytest.mark.asyncio
async def test_events_notices_and_schedule_are_database_immutable(
    collaboration_pg,
):
    factory, service, _, _, data = collaboration_pg
    await start(collaboration_pg)
    await execute(
        factory, service, command(data, "claim", "creator", 2, evidence="proof")
    )
    await execute(factory, service, command(data, "agree", "client", 3))
    for table, column, value in (
        ("financial_collaboration_events", "operation_key", "tampered"),
        ("financial_collaboration_notices", "purpose", "tampered"),
        (
            "financial_collaboration_schedules",
            "release_at",
            datetime(2026, 10, 24, tzinfo=timezone.utc),
        ),
    ):
        with pytest.raises(
            IntegrityError, match="collaboration_fact_immutable"
        ):
            async with factory.begin() as db:
                await db.execute(
                    text(
                        f"update {table} set {column}=:value "
                        "where assignment_id=:id"
                    ),
                    {"value": value, "id": data["assignment"]},
                )


@pytest.mark.asyncio
async def test_current_assignment_and_manager_membership_are_rechecked(
    collaboration_pg,
):
    factory, service, _, _, data = collaboration_pg
    await start(collaboration_pg)
    async with factory.begin() as db:
        await db.execute(
            ManagerOrderModel.__table__.delete().where(
                ManagerOrderModel.user_id == data["manager"]
            )
        )
    with pytest.raises(PermissionError, match="assignment_actor_required"):
        await execute(
            factory,
            service,
            command(data, "request_confirmation", "manager", 2),
        )
    async with factory.begin() as db:
        await db.execute(
            update(ItemAssignmentModel)
            .where(ItemAssignmentModel.assignment_id == data["assignment"])
            .values(valid_to=datetime(2026, 10, 23, tzinfo=timezone.utc))
        )
    with pytest.raises(ValueError, match="assignment_not_current"):
        await execute(
            factory,
            service,
            command(data, "claim", "creator", 2, evidence="proof"),
        )


@pytest.mark.asyncio
async def test_sql_notice_timer_and_maturity_remain_nonmonetary(
    collaboration_pg,
):
    factory, service, repo, clock, data = collaboration_pg
    await start(collaboration_pg)
    await execute(
        factory, service, command(data, "claim", "creator", 2, evidence="proof")
    )
    async with factory.begin() as db:
        notice_id = await db.scalar(
            text(
                "select notice_id from financial_collaboration_notices "
                "where assignment_id=:id"
            ),
            {"id": data["assignment"]},
        )
    await execute(
        factory,
        service,
        command(
            data,
            "notice",
            None,
            3,
            system_actor="collaboration_notifier",
            notice_id=notice_id,
            accepted=True,
            channel="telegram",
            external_reference="message:1",
        ),
    )
    clock.at += timedelta(hours=72)
    async with factory.begin() as db:
        due = await repo.list_due(clock.at, 10, session=db)
        assert data["assignment"] in {
            record.collaboration.assignment_id for record in due
        }
    await execute(
        factory,
        service,
        command(
            data,
            "advance",
            None,
            4,
            key="final",
            system_actor="collaboration_scheduler",
        ),
    )
    clock.at += timedelta(days=14)
    result = await execute(
        factory,
        service,
        command(
            data,
            "advance",
            None,
            5,
            key="mature",
            system_actor="collaboration_scheduler",
        ),
    )
    assert result.collaboration.state.value == "available"
    async with factory.begin() as db:
        assert (
            await db.scalar(
                text(
                    "select count(*) from financial_collaboration_schedules "
                    "where assignment_id=:id"
                ),
                {"id": data["assignment"]},
            )
            == 1
        )
        assert (
            await db.scalar(
                text(
                    "select count(*) from financial_obligations "
                    "where paid_item_id=:id"
                ),
                {"id": data["item"]},
            )
            == 0
        )
        assert await repo.get_notice(uuid4(), session=db) is None
        assert await repo.load_actor(uuid4(), session=db) is None
        with pytest.raises(ValueError, match="invalid_batch_limit"):
            await repo.list_due(clock.at, 0, session=db)


@pytest.mark.asyncio
@pytest.mark.parametrize("collaboration_pg", [False], indirect=True)
async def test_sql_requires_actual_captured_selection_allocation(
    collaboration_pg,
):
    with pytest.raises(ValueError, match="captured_selection_required"):
        await start(collaboration_pg)


@pytest.mark.asyncio
async def test_sql_deduplicates_new_confirmation_keys_by_notice_purpose(
    collaboration_pg,
):
    factory, service, _, _, data = collaboration_pg
    await start(collaboration_pg)
    for version, key in ((2, "request-1"), (3, "request-2")):
        await execute(
            factory,
            service,
            command(data, "request_confirmation", "manager", version, key=key),
        )
    async with factory.begin() as db:
        assert (
            await db.scalar(
                text(
                    "select count(*) from financial_collaboration_notices "
                    "where assignment_id=:id"
                ),
                {"id": data["assignment"]},
            )
            == 2
        )
    with pytest.raises(ValueError, match="assignment_not_found"):
        await execute(
            factory,
            service,
            CollaborationCommand(
                assignment_id=uuid4(),
                action="start",
                operation_key="unknown",
                expected_version=0,
                actor_id=data["client"],
            ),
        )


@pytest.mark.asyncio
async def test_notice_cannot_reference_another_assignments_event(
    collaboration_pg,
):
    from ugc_bot.infrastructure.db.collaboration_models import (
        CollaborationNoticeModel,
    )

    factory, service, _, clock, data = collaboration_pg
    await start(collaboration_pg)
    async with factory.begin() as db:
        foreign_event = await db.scalar(
            text(
                "select event_id from financial_collaboration_events "
                "where assignment_id=:id limit 1"
            ),
            {"id": data["assignment"]},
        )
        await db.execute(
            update(ItemAssignmentModel)
            .where(ItemAssignmentModel.assignment_id == data["assignment"])
            .values(valid_to=clock.at)
        )
        replacement = uuid4()
        db.add(
            ItemAssignmentModel(
                assignment_id=replacement,
                paid_item_id=data["item"],
                version=2,
                creator_id=data["creator"],
                manager_id=data["manager"],
                valid_from=clock.at,
                reason="synthetic next epoch",
                actor_id=data["client"],
            )
        )
    second = dict(data, assignment=replacement)
    await execute(
        factory,
        service,
        command(
            second,
            "assign",
            "client",
            0,
            due_at=clock.at + timedelta(days=2),
            terms_reference="new agreed work",
        ),
    )
    with pytest.raises(
        IntegrityError, match="fk_collaboration_notice_event_scope"
    ):
        async with factory.begin() as db:
            await db.execute(
                CollaborationNoticeModel.__table__.insert().values(
                    notice_id=uuid4(),
                    assignment_id=replacement,
                    source_event_id=foreign_event,
                    purpose="objection",
                    recipient_id=data["client"],
                    created_at=clock.at,
                )
            )


@pytest.mark.asyncio
async def test_status_reads_use_current_authority_and_allow_partys_history(
    collaboration_pg,
):
    factory, service, _, clock, data = collaboration_pg
    current = await start(collaboration_pg)
    async with factory.begin() as db:
        for actor in (data["client"], data["creator"], data["manager"]):
            assert (
                await service.get_for_actor(
                    data["assignment"], actor, session=db
                )
                == current
            )
    async with factory.begin() as db:
        await db.execute(
            ManagerOrderModel.__table__.delete().where(
                ManagerOrderModel.user_id == data["manager"]
            )
        )
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == data["manager"])
            .values(admin=True)
        )
        await db.execute(
            update(ItemAssignmentModel)
            .where(ItemAssignmentModel.assignment_id == data["assignment"])
            .values(valid_to=clock.at)
        )
    async with factory.begin() as db:
        with pytest.raises(
            PermissionError, match="collaboration_view_forbidden"
        ):
            await service.get_for_actor(
                data["assignment"], data["manager"], session=db
            )
        for actor in (data["client"], data["creator"]):
            assert (
                await service.get_for_actor(
                    data["assignment"], actor, session=db
                )
                == current
            )
        assert (
            await service.get_for_actor(uuid4(), data["client"], session=db)
            is None
        )


@pytest.mark.asyncio
async def test_collaboration_downgrade_refuses_immutable_history(
    collaboration_pg, financial_pg_engine
):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from ugc_bot.infrastructure.db.migrations.versions import (
        financial_collaboration_v1,
    )

    await start(collaboration_pg)
    with financial_pg_engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with (
            Operations.context(context),
            pytest.raises(
                RuntimeError,
                match="Cannot discard existing collaboration history",
            ),
        ):
            financial_collaboration_v1.downgrade()
        assert (
            connection.scalar(
                text("select count(*) from financial_collaborations")
            )
            > 0
        )


@pytest.mark.asyncio
async def test_timer_batch_does_not_include_replaced_assignment(
    collaboration_pg,
):
    factory, _, repo, clock, data = collaboration_pg
    await start(collaboration_pg)
    async with factory.begin() as db:
        await db.execute(
            update(ItemAssignmentModel)
            .where(ItemAssignmentModel.assignment_id == data["assignment"])
            .values(valid_to=clock.at)
        )
    async with factory.begin() as db:
        rows = await repo.list_due(
            clock.at + timedelta(days=20), 1000, session=db
        )
    assert data["assignment"] not in {
        row.collaboration.assignment_id for row in rows
    }
