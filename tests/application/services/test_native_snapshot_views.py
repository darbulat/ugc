"""Core snapshot contracts; SQL boundaries below are explicitly synthetic.

Unconnected AsyncSession objects exercise actual adapter statements/checks.
No engine, database, MVCC, concurrency or real read-only protection is tested.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import Select

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.application.partner_view_ports import PartnerReadFacts
from ugc_bot.application.services.campaign_summary_service import (
    CampaignSummaryService,
)
from ugc_bot.application.services.partner_view_service import PartnerViewService
from ugc_bot.application.services.selection_view_service import (
    SelectionViewService,
)
from ugc_bot.infrastructure.db.repositories.campaign_summary import (
    SqlAlchemyCampaignSummaryRepository,
)
from ugc_bot.infrastructure.db.repositories.partner_view import (
    SqlAlchemyPartnerViewRepository,
)
from ugc_bot.infrastructure.db.repositories.selection_view import (
    SqlAlchemySelectionViewRepository,
)

ACTOR, ORDER, OTHER = UUID(int=1), UUID(int=2), UUID(int=3)
NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
FAMILIES = ("partner", "selection", "summary")
NATIVE = {"telegram": "native-tg-123", "max": "native-max-456"}


def principal(platform="telegram", user_id=ACTOR):
    return AuthenticatedMessengerPrincipal(user_id, platform, NATIVE[platform])


def partner_facts(status="active"):
    return PartnerReadFacts(
        ACTOR, status, "abcd1234", 0, 0, (), None, None, None, None
    )


class Transactions:
    def __init__(self):
        self.session, self.events = object(), []

    @asynccontextmanager
    async def transaction(self):
        self.events.append("begin")
        yield self.session
        self.events.append("end")


class PrivateReadReached(Exception):
    """A deliberate stop at the first synthetic private SQL boundary."""


class SnapshotRepository:
    """Pure service boundary with fixed actor facts; no storage emulation."""

    def __init__(self, family, *, proof_required=True, status="active"):
        self.family, self.proof_required = family, proof_required
        self.status, self.sessions, self.prepared = status, [], []
        self.private_reads = 0

    async def begin_snapshot(self, *, session):
        self.prepared.append(session)

    def _result(self, actor_id, session, proof):
        self.sessions.append(session)
        if self.proof_required and proof is None:
            raise ValueError("synthetic_proof_was_dropped")
        require_current_principal(
            proof, actor_id, ACTOR, NATIVE["telegram"], NATIVE["max"]
        )
        self.private_reads += 1
        if self.family == "partner":
            return partner_facts(self.status)
        return {"order_id": ORDER, "history": "synthetic private facts"}

    async def read(
        self,
        actor_id,
        at,
        *,
        network_page,
        assignment_page,
        session,
        principal=None,
    ):
        return self._result(actor_id, session, principal)

    async def view(self, order_id, actor_id, *, session, principal=None):
        assert self.prepared == [session]
        return self._result(actor_id, session, principal)


def service_rig(family, **repository_options):
    repo = SnapshotRepository(family, **repository_options)
    transactions = Transactions()
    clock = SimpleNamespace(now=lambda: NOW)
    if family == "partner":
        service = PartnerViewService(
            repo, clock, {"telegram": "synthetic_bot", "max": "synthetic_max"}
        )
    elif family == "selection":
        service = SelectionViewService(repo, transactions)
    else:
        service = CampaignSummaryService(repo, transactions, clock)
    return service, repo, transactions


async def call_service(family, service, transactions, **kwargs):
    if family == "partner":
        return await service.view(
            ACTOR,
            platform="telegram",
            writes_paused=True,
            session=transactions.session,
            **kwargs,
        )
    return await service.view(ORDER, ACTOR, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_snapshot_services_keep_proof_and_original_session_ownership(
    family, platform
):
    service, repo, transactions = service_rig(family)
    result = await call_service(
        family, service, transactions, principal=principal(platform)
    )
    assert repo.private_reads == 1
    assert repo.sessions == [transactions.session]
    assert repo.prepared == (
        [] if family == "partner" else [transactions.session]
    )
    assert transactions.events == (
        [] if family == "partner" else ["begin", "end"]
    )
    assert NATIVE[platform] not in str(result)
    assert "external_id" not in str(result)
    if family == "partner":
        assert result["actor_id"] == str(ACTOR)
        assert result["financial"]["state"] == "unavailable"
    else:
        assert result["order_id"] == ORDER
        assert result["history"] == "synthetic private facts"
        assert (result.get("as_of") == NOW) == (family == "summary")


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("explicit_none", [False, True])
async def test_snapshot_internal_calls_keep_existing_compatibility(
    family, explicit_none
):
    service, repo, transactions = service_rig(family, proof_required=False)
    result = await call_service(
        family,
        service,
        transactions,
        **({"principal": None} if explicit_none else {}),
    )
    assert result
    assert repo.private_reads == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("proof", [ACTOR, principal(user_id=OTHER)])
async def test_snapshot_service_refuses_wrong_proof_before_private_work(
    family, proof
):
    service, repo, transactions = service_rig(family)
    with pytest.raises(ValueError, match="^financial_principal_changed$"):
        await call_service(family, service, transactions, principal=proof)
    assert repo.private_reads == 0
    assert repo.sessions == []
    assert transactions.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["blocked", "deleted"])
async def test_snapshot_partner_keeps_existing_account_status_denial(status):
    service, repo, transactions = service_rig("partner", status=status)
    with pytest.raises(PermissionError, match="^partner_account_unavailable$"):
        await call_service(
            "partner", service, transactions, principal=principal()
        )
    assert repo.private_reads == 1


class SyntheticResult:
    def __init__(self, actor):
        self.actor, self.mapping = actor, False

    def mappings(self):
        self.mapping = True
        return self

    def one_or_none(self):
        return vars(self.actor) if self.mapping and self.actor else self.actor


class SyntheticSnapshotSession(AsyncSession):
    """Unconnected SQL boundary; no query results establish actual SQL facts."""

    def __init__(self, actor):
        super().__init__()
        self.actor, self.operations = actor, []
        self.actor_selected = False

    def get_bind(self, *args, **kwargs):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    async def execute(self, statement, *args, **kwargs):
        if isinstance(statement, TextClause):
            assert str(statement).startswith("SET TRANSACTION ")
            self.operations.append(("setup", statement))
            return SyntheticResult(None)
        assert isinstance(statement, Select), "synthetic_write_or_lock_added"
        assert statement._for_update_arg is None, "snapshot_row_lock_added"
        if self.actor_selected:
            self.operations.append(("private", statement))
            raise PrivateReadReached()
        self.actor_selected = True
        self.operations.append(("actor", statement))
        return SyntheticResult(self.actor)

    async def scalar(self, statement, *args, **kwargs):
        if not self.actor_selected:
            await self.execute(statement)
            return self.actor.status if self.actor else None
        self.operations.append(("private", statement))
        raise PrivateReadReached()

    async def flush(self, *args, **kwargs):
        raise AssertionError("snapshot_flush_added")


def actor_row(**changes):
    return SimpleNamespace(
        **dict(
            user_id=ACTOR,
            status="active",
            referral_code="abcd1234",
            telegram_id=NATIVE["telegram"],
            max_id=NATIVE["max"],
        )
        | changes
    )


def adapter(family):
    return {
        "partner": SqlAlchemyPartnerViewRepository,
        "selection": SqlAlchemySelectionViewRepository,
        "summary": SqlAlchemyCampaignSummaryRepository,
    }[family]()


async def call_adapter(family, db, **kwargs):
    repository = adapter(family)
    if family == "partner":
        return await repository.read(
            ACTOR, NOW, network_page=0, assignment_page=0, session=db, **kwargs
        )
    await repository.begin_snapshot(session=db)
    return await repository.view(ORDER, ACTOR, session=db, **kwargs)


def assert_first_actor_projection(db):
    assert [kind for kind, _ in db.operations[:2]] == ["setup", "actor"]
    setup, query = [statement for _, statement in db.operations[:2]]
    assert "REPEATABLE READ" in str(setup) and "READ ONLY" in str(setup)
    assert {"user_id", "status", "telegram_id", "max_id"} <= set(
        query.selected_columns.keys()
    )
    assert query._for_update_arg is None


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("change", ["remap", "clear", "actor", "absent"])
async def test_snapshot_native_change_denies_at_first_actor_before_private_sql(
    family, platform, change
):
    changes = (
        {"user_id": OTHER}
        if change == "actor"
        else {
            "telegram_id" if platform == "telegram" else "max_id": None
            if change == "clear"
            else "changed-native"
        }
    )
    actor = None if change == "absent" else actor_row(**changes)
    async with SyntheticSnapshotSession(actor) as db, db.begin():
        with pytest.raises(ValueError, match="^financial_principal_changed$"):
            await call_adapter(family, db, principal=principal(platform))
        assert_first_actor_projection(db)
        assert len(db.operations) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("status", ["active", "pause", "bot_blocked"])
async def test_snapshot_valid_native_reaches_existing_private_read_boundary(
    family, platform, status
):
    async with (
        SyntheticSnapshotSession(actor_row(status=status)) as db,
        db.begin(),
    ):
        with pytest.raises(PrivateReadReached):
            await call_adapter(family, db, principal=principal(platform))
        assert_first_actor_projection(db)
        assert [kind for kind, _ in db.operations] == [
            "setup",
            "actor",
            "private",
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("proof", [ACTOR, principal(user_id=OTHER)])
async def test_snapshot_adapter_rejects_uuid_or_foreign_proof_before_private(
    family, proof
):
    async with SyntheticSnapshotSession(actor_row()) as db, db.begin():
        with pytest.raises(ValueError, match="^financial_principal_changed$"):
            await call_adapter(family, db, principal=proof)
        assert len(db.operations) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
async def test_snapshot_adapter_trusted_internal_call_needs_no_native_mapping(
    family,
):
    async with (
        SyntheticSnapshotSession(
            actor_row(telegram_id=None, max_id=None)
        ) as db,
        db.begin(),
    ):
        with pytest.raises(PrivateReadReached):
            await call_adapter(family, db)


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_snapshot_native_denial_precedes_existing_inactive_denial(
    family, platform
):
    async with (
        SyntheticSnapshotSession(
            actor_row(status="deleted", telegram_id=None, max_id=None)
        ) as db,
        db.begin(),
    ):
        with pytest.raises(ValueError, match="^financial_principal_changed$"):
            await call_adapter(family, db, principal=principal(platform))
        assert len(db.operations) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["selection", "summary"])
@pytest.mark.parametrize("status", ["blocked", "deleted"])
async def test_snapshot_existing_inactive_semantics_are_retained(
    family, status
):
    async with (
        SyntheticSnapshotSession(actor_row(status=status)) as db,
        db.begin(),
    ):
        with pytest.raises(
            PermissionError,
            match="^(selection_client|summary_actor)_inactive$",
        ):
            await call_adapter(family, db, principal=principal())
        assert len(db.operations) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
async def test_snapshot_existing_missing_actor_internal_semantics_remain(
    family,
):
    async with SyntheticSnapshotSession(None) as db, db.begin():
        if family == "partner":
            assert await call_adapter(family, db) is None
        else:
            with pytest.raises(PermissionError, match="inactive"):
                await call_adapter(family, db)
        assert len(db.operations) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_snapshot_uses_only_the_authenticated_platform_mapping(
    family, platform
):
    other_field = "max_id" if platform == "telegram" else "telegram_id"
    async with (
        SyntheticSnapshotSession(actor_row(**{other_field: None})) as db,
        db.begin(),
    ):
        with pytest.raises(PrivateReadReached):
            await call_adapter(family, db, principal=principal(platform))
        assert len(db.operations) == 3


class SyntheticMembershipSession(SyntheticSnapshotSession):
    """Fixed absent role/order/membership facts; no database implementation."""

    def __init__(self, actor, *, order=None):
        super().__init__(actor)
        self.order = order

    async def execute(self, statement, *args, **kwargs):
        if not self.actor_selected or isinstance(statement, TextClause):
            return await super().execute(statement, *args, **kwargs)
        assert isinstance(statement, Select)
        assert statement._for_update_arg is None
        self.operations.append(("scope", statement))
        return SyntheticResult(
            SimpleNamespace(**self.order) if self.order else None
        )

    async def scalar(self, statement, *args, **kwargs):
        assert self.actor_selected
        assert isinstance(statement, Select)
        assert statement._for_update_arg is None
        self.operations.append(("membership", statement))
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_snapshot_selection_keeps_current_advertiser_role_requirement(
    platform,
):
    async with SyntheticMembershipSession(actor_row()) as db, db.begin():
        with pytest.raises(
            PermissionError, match="^selection_client_role_required$"
        ):
            await call_adapter("selection", db, principal=principal(platform))
        assert [kind for kind, _ in db.operations] == [
            "setup",
            "actor",
            "membership",
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "source", ["missing", "foreign", "revoked_client_role"]
)
async def test_snapshot_summary_keeps_order_and_current_membership_scope(
    platform, source
):
    order = (
        None
        if source == "missing"
        else dict(
            order_id=ORDER,
            advertiser_id=ACTOR if source == "revoked_client_role" else OTHER,
            financial_version="published-policy",
        )
    )
    async with (
        SyntheticMembershipSession(actor_row(), order=order) as db,
        db.begin(),
    ):
        with pytest.raises(LookupError, match="^summary_not_found$"):
            await call_adapter("summary", db, principal=principal(platform))
        assert_first_actor_projection(db)
        assert [kind for kind, _ in db.operations] == [
            "setup",
            "actor",
            "scope",
        ] + (
            []
            if source == "missing"
            else ["membership"]
            if source == "foreign"
            else ["membership", "membership"]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
async def test_snapshot_actor_statement_disables_autoflush_before_proof_check(
    family,
):
    async with (
        SyntheticSnapshotSession(actor_row(telegram_id=None)) as db,
        db.begin(),
    ):
        with pytest.raises(ValueError, match="^financial_principal_changed$"):
            await call_adapter(family, db, principal=principal())
        assert (
            db.operations[1][1].get_execution_options().get("autoflush")
            is False
        )
