"""Actual current-head correction producers; bank observations are synthetic."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from uuid import UUID, uuid4

from sqlalchemy import event, insert, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.helpers.corrections import captured_order, refund_command, rows
from ugc_bot.application.correction_ports import (
    MatchSelectionRefund,
    RecordManualRefundObservation,
    ReviewSelectionRefund,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.correction_service import CorrectionService
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.correction_models import TABLE_MAP
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.repositories.corrections import (
    SqlAlchemyCorrectionRepository,
)
from ugc_bot.infrastructure.db.repositories.physical_proofs import (
    PROOFS,
    SqlAlchemyPhysicalProofRepository,
)


class Runtime:
    def __init__(self, env, facts):
        self.env, self.facts = env, facts
        self.repo = SqlAlchemyCorrectionRepository()
        self.proofs = SqlAlchemyPhysicalProofRepository(
            "synthetic-correction-bank",
            "synthetic-correction-account",
            env["clock"],
        )
        self.service = CorrectionService(self.repo, self.proofs, env["clock"])

    def principal(self, actor, platform="telegram"):
        with Session(self.env["pg"]) as db:
            user = db.get(UserModel, actor)
            external = (
                user.telegram_id if platform == "telegram" else user.max_id
            )
        return AuthenticatedMessengerPrincipal(actor, platform, external)

    async def execute(self, command, *, principal=None, session=None):
        proof = principal or self.principal(command.actor_id)
        if session is not None:
            return await self.service.execute(
                command, session=session, principal=proof
            )
        async with self.env[
            "container"
        ].transaction_manager.transaction() as db:
            return await self.service.execute(
                command, session=db, principal=proof
            )

    async def request(self, **changes):
        command = refund_command(self.facts)
        async with self.env[
            "container"
        ].transaction_manager.transaction() as db:
            scope = await self.repo.discover_scope(command, session=db)
        return replace(
            command, expected_source_hash=scope.source_hash, **changes
        )

    def review(self, state, **changes):
        return ReviewSelectionRefund(
            **(
                dict(
                    actor_id=self.env["admin"].user_id,
                    operation_key="correction-review:" + uuid4().hex,
                    reason="Admin reviews the expired captured selection",
                    case_id=UUID(state["case_id"]),
                    expected_version=state["version"],
                    expected_source_hash=state["source_hash"],
                    decision="approve",
                    evidence_reference="synthetic:admin-review",
                    evidence_hash="b" * 64,
                )
                | changes
            )
        )

    def observation(self, state=None, **changes):
        return RecordManualRefundObservation(
            **(
                dict(
                    actor_id=self.env["admin"].user_id,
                    operation_key="correction-observation:" + uuid4().hex,
                    reason="Retain declared synthetic actual bank report",
                    case_id=UUID(state["case_id"]) if state else None,
                    known_order_id=self.facts["order"].order_id,
                    known_capture_intent_id=self.facts["invoice_id"],
                    original_payment_reference=self.facts[
                        "payment"
                    ].external_id,
                    bank_account_label="synthetic-correction-account",
                    bank_reference="synthetic:refund:" + uuid4().hex,
                    amount_minor=250000,
                    currency="RUB",
                    occurred_at=self.env["clock"].now(),
                    reported_component="selection",
                    evidence_reference="synthetic:bank-report",
                    evidence_hash="c" * 64,
                    expected_version=state["version"] if state else None,
                )
                | changes
            )
        )

    def match(self, state, intent, observation, **changes):
        return MatchSelectionRefund(
            **(
                dict(
                    actor_id=self.env["admin"].user_id,
                    operation_key="correction-match:" + uuid4().hex,
                    reason="Fresh exact full selection match",
                    case_id=UUID(state["case_id"]),
                    intent_id=UUID(intent["intent_id"]),
                    observation_id=UUID(observation["observation_id"]),
                    expected_version=state["version"],
                    expected_source_hash=state["source_hash"],
                    evidence_reference="synthetic:match",
                    evidence_hash="d" * 64,
                )
                | changes
            )
        )

    async def approved(self):
        requested = await self.execute(await self.request())
        return await self.execute(self.review(requested))

    def rows(self, kind, **where):
        return rows(self.env, TABLE_MAP[kind].name, **where)

    def claims(self, intent_id):
        with Session(self.env["pg"]) as db:
            return [
                dict(row)
                for row in db.execute(
                    select(PROOFS).where(PROOFS.c.intent_id == UUID(intent_id))
                ).mappings()
            ]


async def runtime(env, *, referred=True):
    from ugc_bot.infrastructure.db.repositories.financial_capture import (
        intent_id,
    )

    facts = await captured_order(env, referred=referred)
    facts["invoice_id"] = intent_id(facts["order"].order_id)
    with Session(env["pg"]) as db, db.begin():
        for actor in (env["user"].user_id, env["admin"].user_id):
            db.get(UserModel, actor).max_id = "max:" + actor.hex
    return Runtime(env, facts)


async def pending_runtime(env):
    """Actual invoice before receipt; no captured authority is fabricated."""
    from tests.postgres_financial.test_order_intake import command, service
    from ugc_bot.application.services.creator_identity_history_service import (
        CreatorIdentityHistoryService,
    )
    from ugc_bot.application.services.financial_policy_service import (
        FinancialPolicyService,
    )
    from ugc_bot.infrastructure.db.models import PaymentModel
    from ugc_bot.infrastructure.db.repositories.financial_capture import (
        SqlAlchemyFinancialCaptureRepository,
        intent_id,
    )

    request = command(env)
    order = await service(env).create(request)
    payments = env["container"].build_bot_services()["payment_service"]
    payments.capture_repository = SqlAlchemyFinancialCaptureRepository(
        FinancialPolicyService(env["config"].financial),
        history=CreatorIdentityHistoryService(
            env["repos"]["creator_identity_history_repo"]
        ),
    )
    payments.capture_account = "synthetic-correction-merchant"
    async with env["container"].transaction_manager.transaction() as db:
        await payments.capture_repository.issue(
            order.order_id,
            env["user"].user_id,
            payments.capture_account,
            session=db,
        )
    with Session(env["pg"]) as db:
        payment = db.scalar(
            select(PaymentModel).where(PaymentModel.order_id == order.order_id)
        )
    facts = dict(
        order=order,
        request=request,
        payment=payment,
        client=env["user"].user_id,
        invoice_id=intent_id(order.order_id),
    )
    return Runtime(env, facts)


@asynccontextmanager
async def statements(rt):
    """Trace only this Container's current caller connection."""
    engine = rt.env["container"].session_factory.kw["bind"]
    seen = []

    def before(conn, cursor, statement, parameters, context, many):
        if conn.info.get("correction_task4_reader"):
            user = (
                parameters.get("user_id_1")
                if isinstance(parameters, dict)
                else None
            )
            seen.append((statement, user))

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)


async def backend(db):
    await db.execute(text("SET LOCAL statement_timeout='5s'"))
    await db.execute(text("SET LOCAL lock_timeout='4s'"))
    return await db.scalar(text("SELECT pg_backend_pid()"))


async def blocked(observer, waiting, blocker):
    for _ in range(200):
        pids = await observer.scalar(
            text("SELECT pg_blocking_pids(:pid)"), {"pid": waiting}
        )
        if blocker in pids:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        "actual correction User barrier did not establish PID wait"
    )


async def authority_race(rt, *, entry, platform, change, first):
    """Actual Container reader transaction and independent writer/observer."""
    request = await rt.request()
    requested = await rt.execute(request)
    review = rt.review(requested)
    await rt.execute(review)
    actor = request.actor_id if change == "owner" else review.actor_id
    proof = rt.principal(actor, platform)
    tm = rt.env["container"].transaction_manager
    engine = create_async_engine(rt.env["pg"].url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    selected = request if change == "owner" else review
    async with tm.transaction() as db:
        scope = await rt.repo.discover_scope(selected, session=db)

    async def call(db):
        if entry == "execute":
            return await rt.execute(selected, principal=proof, session=db)
        if entry == "case":
            return await rt.service.get_for_actor(
                UUID(requested["case_id"]), actor, session=db, principal=proof
            )
        return await rt.service.operation_for_actor(
            actor, selected.operation_key, session=db, principal=proof
        )

    async def mutate(db):
        await db.execute(
            select(UserModel.user_id)
            .where(UserModel.user_id == actor)
            .with_for_update()
        )
        if change == "native":
            field = "telegram_id" if platform == "telegram" else "max_id"
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == actor)
                .values(**{field: "remapped:" + uuid4().hex})
            )
        elif change == "status":
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == actor)
                .values(status="blocked")
            )
        elif change == "admin":
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == actor)
                .values(admin=False)
            )
        elif change == "owner":
            orders = Base.metadata.tables["orders"]
            await db.execute(
                update(orders)
                .where(orders.c.order_id == scope.order_id)
                .values(advertiser_id=rt.facts["stranger"])
            )
        # Private fixture mutation creates a simultaneous new source user.
        managers = Base.metadata.tables["manager_orders"]
        await db.execute(
            insert(managers).values(
                order_id=scope.order_id,
                user_id=rt.facts["stranger"],
                created_at=text("CURRENT_TIMESTAMP"),
            )
        )

    expected = {
        "native": "financial_principal_changed",
        "status": "correction_active_actor_required",
        "admin": "correction_active_admin_required"
        if entry != "case"
        else "correction_own_client_required",
        "owner": "correction_own_client_required",
        "source": "correction_scope_changed_retry_required",
    }[change]
    task = None
    ready = asyncio.Future()
    try:
        async with statements(rt) as seen:
            if first == "writer":
                async with factory.begin() as writer:
                    writer_pid = await backend(writer)
                    await mutate(writer)

                    async def read():
                        async with tm.transaction() as db:
                            reader_pid = await backend(db)
                            connection = await db.connection()
                            connection.info["correction_task4_reader"] = True
                            ready.set_result(reader_pid)
                            try:
                                try:
                                    await call(db)
                                except ValueError as exc:
                                    assert exc.args == (expected,)
                                else:
                                    raise AssertionError(
                                        "changed authority admitted"
                                    )
                            finally:
                                connection.info.pop(
                                    "correction_task4_reader", None
                                )

                    task = asyncio.create_task(read())
                    reader_pid = await asyncio.wait_for(ready, 2)
                    assert reader_pid != writer_pid
                    await blocked(writer, reader_pid, writer_pid)
                    assert not task.done()
                    await writer.commit()
                    await asyncio.wait_for(task, 4)
                assert change == "source" or not any(
                    "INSERT INTO financial_wallets" in sql for sql, _ in seen
                )
            else:
                async with tm.transaction() as db:
                    reader_pid = await backend(db)
                    connection = await db.connection()
                    connection.info["correction_task4_reader"] = True
                    try:
                        assert await call(db) is not None
                    finally:
                        connection.info.pop("correction_task4_reader", None)

                    async def write():
                        async with factory.begin() as writer:
                            ready.set_result(await backend(writer))
                            await mutate(writer)

                    task = asyncio.create_task(write())
                    writer_pid = await asyncio.wait_for(ready, 2)
                    assert reader_pid != writer_pid
                    await blocked(db, writer_pid, reader_pid)
                    assert not task.done()
                    await db.commit()
                    await asyncio.wait_for(task, 4)
            locked = [
                uid
                for sql, uid in seen
                if "FROM users" in sql and "FOR NO KEY UPDATE" in sql
            ]
            expected_users = sorted(scope.prospective_user_ids, key=str)
            assert locked[: len(expected_users)] == expected_users
            assert set(locked).issubset(expected_users)
        return dict(
            entry=entry,
            platform=platform,
            change=change,
            first=first,
            reader_pid=reader_pid,
            writer_pid=writer_pid,
            completed=True,
            user_order=[str(u) for u in expected_users],
        )
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


@contextmanager
def corrupt_case(rt, case_id, **changes):
    """Declared raw private corruption; normal producers cannot mutate facts."""
    table = TABLE_MAP["cases"]
    original = rt.rows("cases", case_id=case_id)[0]

    def write(values):
        with Session(rt.env["pg"]) as db, db.begin():
            db.execute(
                text(
                    "ALTER TABLE financial_correction_cases "
                    "DISABLE TRIGGER correction_fact_immutable"
                )
            )
            db.execute(
                update(table).where(table.c.case_id == case_id).values(**values)
            )
            db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            db.execute(
                text(
                    "ALTER TABLE financial_correction_cases "
                    "ENABLE TRIGGER correction_fact_immutable"
                )
            )

    write(changes)
    try:
        yield
    finally:
        write({key: original[key] for key in changes})
