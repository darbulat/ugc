"""Actual approval producers with declared synthetic bank reports."""

from uuid import UUID

from tests.helpers.correction_runtime_pg import (
    Runtime,
    pending_runtime,
    runtime,
)
from tests.helpers.corrections import captured_order, rows
from ugc_bot.infrastructure.db.correction_approval_models import TABLE_MAP


class ApprovalRuntime(Runtime):
    def approval_rows(self, kind, **where):
        return rows(self.env, TABLE_MAP[kind].name, **where)

    @classmethod
    def from_runtime(cls, rt):
        return cls(rt.env, rt.facts)


async def approval_runtime(env, *, early=False):
    rt = await (pending_runtime(env) if early else runtime(env))
    if early:
        from sqlalchemy.orm import Session

        from ugc_bot.infrastructure.db.models import UserModel

        with Session(env["pg"]) as db, db.begin():
            for actor in (env["user"].user_id, env["admin"].user_id):
                db.get(UserModel, actor).max_id = "max:" + actor.hex
    return ApprovalRuntime.from_runtime(rt)


async def capture_pending(rt):
    actual = await captured_order(
        rt.env, existing=(rt.facts["request"], rt.facts["order"])
    )
    rt.facts.update(actual)


async def create_match(rt, *, platform="telegram"):
    requested = await rt.execute(await rt.request())
    approved = await rt.execute(
        rt.review(requested),
        principal=rt.principal(rt.env["admin"].user_id, platform),
    )
    observed = await rt.execute(rt.observation(approved))
    matched = await rt.execute(rt.match(observed, approved, observed))
    return requested, approved, observed, matched


async def genuine_approved_match(env, facts, repo, db, *, selected=None):
    """Current service provenance for existing economic guard helper inputs."""
    from dataclasses import replace

    from tests.helpers.corrections import refund_command
    from ugc_bot.application.correction_ports import correction_command_id
    from ugc_bot.infrastructure.db.repositories.financial_capture import (
        intent_id,
    )

    facts = facts | {"invoice_id": intent_id(facts["order"].order_id)}
    rt = ApprovalRuntime(env, facts)
    rt.repo = repo
    rt.service.repository = repo
    command = refund_command(facts, items=selected)
    scope = await repo.discover_scope(command, session=db)
    requested = await rt.execute(
        replace(command, expected_source_hash=scope.source_hash), session=db
    )
    approved = await rt.execute(rt.review(requested), session=db)
    observed = await rt.execute(
        rt.observation(approved, amount_minor=scope.bundle.total_minor),
        session=db,
    )
    match_command = rt.match(observed, approved, observed)
    matched = await rt.execute(match_command, session=db)
    return dict(
        scope=scope,
        case_id=UUID(matched["case_id"]),
        match_id=UUID(matched["match_id"]),
        intent_id=UUID(approved["intent_id"]),
        observation_id=UUID(observed["observation_id"]),
        command_id=correction_command_id(match_command),
    )


def archived_command(writer, command):
    """Instantiate the archived dispatch class, including only init fields."""
    from dataclasses import fields

    kind = getattr(writer.ports, type(command).__name__)
    return kind(
        **{
            field.name: getattr(command, field.name)
            for field in fields(kind)
            if field.init
        }
    )


def installed_approval_guard(engine):
    from sqlalchemy import text

    with engine.connect() as db:
        return dict(
            functions=db.execute(
                text(
                    """SELECT proname,prosrc FROM pg_proc
                    WHERE pronamespace=current_schema()::regnamespace
                    AND proname LIKE 'correction_%' ORDER BY proname"""
                )
            ).all(),
            triggers=db.execute(
                text(
                    """SELECT c.relname,t.tgname,t.tgdeferrable,
                    t.tginitdeferred,t.tgtype FROM pg_trigger t
                    JOIN pg_class c ON c.oid=t.tgrelid
                    WHERE c.relnamespace=current_schema()::regnamespace
                    AND NOT t.tgisinternal AND t.tgname IN
                    ('correction_approval_guard','correction_application_guard',
                    'correction_fact_immutable') ORDER BY c.relname,t.tgname"""
                )
            ).all(),
        )


def alter_fact(rt, kind, mutation):
    """Inject a malformed SQL write after genuine service validation."""
    from contextlib import contextmanager
    from copy import deepcopy

    @contextmanager
    def altered():
        original = rt.repo.append_fact

        async def append(name, values, *, session):
            if name == kind:
                values = mutation(deepcopy(values))
                if values is None:
                    return
            await original(name, values, session=session)

        rt.repo.append_fact = append
        try:
            yield
        finally:
            rt.repo.append_fact = original

    return altered()


def corrupt_event_hash(rt, field="result_state_hash"):
    """Inject a corrupt event INSERT through the real Container connection."""
    from contextlib import contextmanager

    from sqlalchemy import event
    from sqlalchemy.sql.dml import Insert

    @contextmanager
    def corrupted():
        engine = rt.env["container"].session_factory.kw["bind"].sync_engine

        def before(conn, statement, multiparams, params, options):
            if (
                isinstance(statement, Insert)
                and statement.table.name == "financial_correction_events"
            ):
                statement = statement.values(**{field: "f" * 64})
            return statement, multiparams, params

        event.listen(engine, "before_execute", before, retval=True)
        try:
            yield
        finally:
            event.remove(engine, "before_execute", before)

    return corrupted()
