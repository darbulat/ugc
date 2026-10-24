"""Snapshot boundaries preserve broken queue authority and SQL bounds."""

import importlib
from contextlib import asynccontextmanager
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import pytest


def module():
    try:
        return importlib.import_module(
            "ugc_bot.infrastructure.db.repositories.payout_views"
        )
    except ModuleNotFoundError:
        pytest.fail("read-only payout SQL snapshot adapter is missing")


class Session:
    def __init__(self, dialect="postgresql"):
        self.calls = []
        self.dialect = dialect

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name=self.dialect))

    @asynccontextmanager
    async def begin(self):
        self.calls.append("begin")
        yield

    async def execute(self, query, *args, **kwargs):
        self.calls.append(str(query))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.calls.append("closed")


@pytest.mark.asyncio
async def test_snapshot_sets_read_only_repeatable_read_before_any_select():
    m = module()
    session = Session()
    async with m.SqlAlchemyPayoutViewRepository(
        lambda: session
    ).snapshot() as reader:
        assert reader.session is session
        assert session.calls == [
            "begin",
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        ]
    assert session.calls[-1] == "closed"


@pytest.mark.asyncio
async def test_reader_refuses_a_nonpostgres_database_before_any_query():
    m = module()
    session = Session("sqlite")
    with pytest.raises(ValueError, match="payout_source_unavailable"):
        async with m.SqlAlchemyPayoutViewRepository(lambda: session).snapshot():
            pytest.fail("unsafe reader session yielded")
    assert session.calls == ["closed"]


def test_queue_query_preserves_broken_rows_before_its_sql_bound():
    m = module()
    from sqlalchemy.dialects.postgresql import dialect

    from ugc_bot.application.payout_view_ports import Page

    query = m.requests_query(None, Page(limit=100), None, queue=True)
    sql = str(query.compile(dialect=dialect()))
    assert (
        "LEFT OUTER JOIN" in sql
        and "financial_payout_events" in sql
        and "financial_payout_states" in sql
    )
    assert "jsonb_build_object" in sql and "coalesce" in sql
    assert query._limit_clause.value == 101
    own = m.requests_query(uuid4(), Page(limit=2), None, queue=False)
    assert own._limit_clause.value == 3


class PhysicalResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self.rows)

    def one_or_none(self):
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None


class PhysicalSession:
    """No engine: retain real source preflight and adapter conversion."""

    def __init__(self, missing=None, rows=None):
        m = module()
        self.columns = {
            table.name: set(table.c.keys())
            for table in m.m.Base.metadata.tables.values()
        }
        if missing:
            table, column = missing
            if column is None:
                self.columns.pop(table)
            else:
                self.columns[table].remove(column)
        self.rows = rows or {}

    async def execute(self, query):
        from sqlalchemy.sql.elements import TextClause

        if isinstance(query, TextClause):
            return PhysicalResult(
                [
                    (table, column)
                    for table, cols in self.columns.items()
                    for column in cols
                ]
            )
        first = next(iter(query.selected_columns))
        return PhysicalResult(self.rows.get(first.table.name, ()))

    async def scalar(self, query):
        column = next(iter(query.selected_columns))
        if column.table.name == "users" and column.name == "status":
            return "active"
        return None


def money_snapshot(facts, missing):
    m = module()
    financial = facts["financial"]
    rows = {
        "financial_obligations": [
            dict(
                id=o.basis.obligation_id,
                recipient_id=o.basis.recipient_id,
                currency="RUB",
                amount_minor=o.basis.amount_minor,
                paid_item_id=o.paid_item_id,
            )
            for o in financial.obligations
        ],
        "financial_movements": [asdict(row) for row in financial.movements],
        "financial_wallets": [
            {
                name + "_minor": amount
                for name, amount in financial.wallet.items()
            }
        ],
    }
    return m.PayoutSnapshot(PhysicalSession(missing, rows))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing",
    [
        ("financial_payout_commands", None),
        ("financial_payout_commands", "result"),
        ("financial_obligations", "snapshot_id"),
    ],
)
async def test_command_source_blocks_actions_but_preserves_balance(
    missing,
):
    from tests.unit.test_payout_view_service import request_facts, setup

    _, _, service, repo, principal = setup(admin=True)
    fact = request_facts(repo)
    service.crypto = SimpleNamespace(open=lambda *args: {"private": "discard"})
    repo.reader.financial = money_snapshot(repo.reader.facts, missing).financial
    context = await service.context(principal)
    preview = await service.reserve_preview(
        principal, fact.row["requisites_id"], 50
    )
    detail = await service.detail(principal, fact.row["request_id"])
    assert context["financial"]["state"] == "ready"
    assert context["financial"]["balances"]["available_minor"] == "100"
    assert not context["capabilities"]["begin_request"]
    assert not preview["can_reserve"]
    assert preview["blockers"] == ["payout_source_unavailable"]
    for action in ("review", "reject", "start"):
        assert action not in detail["allowed_actions"]
        assert "payout_source_unavailable" in detail["action_blockers"][action]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "column", ["country", "max_chat_id", "username", "referral_payout_rate"]
)
async def test_observation_needs_writer_columns_but_identity_stays_narrow(
    column,
):
    from tests.unit.test_payout_view_service import request_facts, setup

    m = module()
    _, _, service, repo, principal = setup(admin=True)
    fact = request_facts(repo, "executing", broken=True)
    rows = {
        "users": [
            dict(
                user_id=principal.actor_id,
                native="123",
                status="active",
                admin=True,
            )
        ],
        "financial_payout_intents": list(fact.retained_intents),
    }
    snapshot = m.PayoutSnapshot(PhysicalSession(("users", column), rows))
    assert (await snapshot.actor(principal)).actor_id == principal.actor_id
    actual = await snapshot._request(fact.row)
    assert actual.retained_intents
    repo.reader.facts["request"] = actual
    service.config.payouts_enabled = False
    result = await service.detail(principal, fact.row["request_id"])
    assert "record_observation" not in result["allowed_actions"]
    assert result["action_blockers"]["record_observation"] == [
        "payout_observation_source_unavailable"
    ]


@pytest.mark.asyncio
async def test_invalid_journal_row_is_an_explicit_source_integrity_stop():
    from tests.unit.test_payout_view_service import setup

    _, _, _, repo, principal = setup()
    snapshot = money_snapshot(repo.reader.facts, None)
    snapshot.session.rows["financial_movements"][0]["amount_minor"] = 0
    result = await snapshot.financial(principal.actor_id)
    assert result.source_blockers == ("payout_source_integrity_required",)
    assert not result.movements


@pytest.mark.asyncio
async def test_empty_raw_sources_cannot_erase_an_actual_stored_request():
    m = module()
    snapshot = m.PayoutSnapshot(PhysicalSession())

    async def scalar(query):
        first = next(iter(query.selected_columns))
        return (
            uuid4() if first.table.name == "financial_payout_requests" else None
        )

    snapshot.session.scalar = scalar
    result = await snapshot.financial(uuid4())
    assert result.source_blockers == ("payout_source_integrity_required",)


def test_bad_execution_uuid_is_not_retained_event_authority():
    from tests.unit.test_payout_view_service import NOW

    m, request = module(), uuid4()
    event = dict(
        version=3,
        state="executing",
        recorded_at=NOW,
        details={
            "projection": dict(
                request_id=str(request),
                version=3,
                state="executing",
                execution_id="invalid",
                block_reason="",
            )
        },
    )
    assert m.PayoutSnapshot._event_proof(event, request) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing",
    [
        ("financial_payout_commands", None),
        ("financial_payout_commands", "result"),
        ("users", "country"),
    ],
)
async def test_common_physical_sources_gate_all_ordinary_command_hints(missing):
    from tests.unit.test_payout_view_service import request_facts, setup

    _, _, service, repo, principal = setup(admin=True)
    fact = request_facts(repo)
    service.crypto = SimpleNamespace(open=lambda *args: {"private": "discard"})
    snapshot = money_snapshot(repo.reader.facts, missing)
    repo.reader.financial = snapshot.financial

    async def physical(kind):
        return await snapshot.command_blockers(kind)

    repo.reader.command_blockers = physical
    context = await service.context(principal)
    detail = await service.detail(principal, fact.row["request_id"])
    assert context["financial"]["state"] == "ready"
    assert not context["capabilities"]["store_requisites"]
    assert not context["capabilities"]["publish_requirements"]
    assert "escalate" not in detail["allowed_actions"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing",
    [
        ("financial_obligations", "snapshot_id"),
        ("financial_wallets", "version"),
        ("order_items", "paid_item_id"),
    ],
)
async def test_escalation_requires_its_physical_money_lock_sources(missing):
    from tests.unit.test_payout_view_service import request_facts, setup

    _, _, service, repo, principal = setup(admin=True)
    fact = request_facts(repo)
    service.crypto = SimpleNamespace(open=lambda *args: {"private": "discard"})
    snapshot = money_snapshot(repo.reader.facts, missing)
    repo.reader.financial = snapshot.financial

    async def physical(kind):
        return await snapshot.command_blockers(kind)

    repo.reader.command_blockers = physical
    context = await service.context(principal)
    detail = await service.detail(principal, fact.row["request_id"])
    assert context["capabilities"]["store_requisites"]
    assert context["capabilities"]["publish_requirements"]
    assert "escalate" not in detail["allowed_actions"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing",
    [
        ("financial_payout_terms_documents", "content_text"),
        ("financial_payout_requirement_contracts", "field_definitions"),
        ("financial_payout_requisites_acceptances", None),
    ],
)
async def test_publication_requires_its_actual_document_sources(missing):
    from tests.unit.test_payout_view_service import readable, setup

    _, _, service, repo, principal = setup(admin=True)
    readable(repo)
    snapshot = money_snapshot(repo.reader.facts, missing)

    async def physical(kind):
        return await snapshot.command_blockers(kind)

    repo.reader.command_blockers = physical
    context = await service.context(principal)
    assert not context["capabilities"]["publish_requirements"]
