"""Payout snapshots use existing facts only; never lock, upsert or repair."""

from contextlib import asynccontextmanager
from dataclasses import fields
from uuid import UUID

import sqlalchemy as sa

from ugc_bot.application.financial_ports import JournalMovement, ObligationBasis
from ugc_bot.application.payout_errors import public_payout_code
from ugc_bot.application.payout_view_ports import (
    FinancialRead,
    ReadActor,
    ReadAllocation,
    ReadObligation,
    RequestRead,
    RequirementsRead,
    RequisiteRead,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    BUCKETS,
)
from ugc_bot.infrastructure.db import models as m
from ugc_bot.infrastructure.db.payout_contract_models import TABLE_MAP as C
from ugc_bot.infrastructure.db.payout_models import TABLE_MAP as P
from ugc_bot.infrastructure.db.repositories.payout_contracts import (
    SqlAlchemyPayoutContractRepository,
)
from ugc_bot.infrastructure.db.repositories.work_entitlements import (
    SqlAlchemyWorkEntitlementRepository,
)

IDENTITY = {"users": ("user_id", "telegram_id", "max_id", "status", "admin")}
AMOUNTS = {
    "financial_obligations": (
        "id",
        "recipient_id",
        "currency",
        "amount_minor",
        "paid_item_id",
    ),
    "financial_movements": tuple(
        m.Base.metadata.tables["financial_movements"].c.keys()
    ),
    "financial_wallets": tuple(
        m.Base.metadata.tables["financial_wallets"].c.keys()
    ),
}
COMMAND_SOURCES = {
    P["commands"].name: tuple(P["commands"].c.keys()),
    "users": tuple(m.UserModel.__table__.c.keys()),
}
REQUIREMENTS = {P["requirements"].name: tuple(P["requirements"].c.keys())}
CONTRACTS = {table.name: tuple(table.c.keys()) for table in C.values()}
REQUESTS = {
    P["requests"].name: tuple(P["requests"].c.keys()),
    P["requisites"].name: tuple(P["requisites"].c.keys()),
}
AUTHORITY = {P[n].name: tuple(P[n].c.keys()) for n in ("states", "events")}
MONEY_LOCK_SOURCES = {
    "financial_wallets": AMOUNTS["financial_wallets"],
    "financial_obligations": tuple(
        m.Base.metadata.tables["financial_obligations"].c.keys()
    ),
    "order_items": ("paid_item_id",),
} | AUTHORITY
STORE_SOURCES = (
    REQUIREMENTS
    | {P["requisites"].name: tuple(P["requisites"].c.keys())}
    | CONTRACTS
)
PUBLICATION_SOURCES = (
    REQUIREMENTS
    | {C[n].name: tuple(C[n].c.keys()) for n in ("documents", "bindings")}
    # The frozen availability query requires this relation, but publication
    # never reads or writes its columns.
    | {C["acceptances"].name: ()}
)
PAYOUT_PROOF = {
    P[n].name: tuple(P[n].c.keys())
    for n in (
        "requests",
        "movement_links",
        "allocations",
        "intents",
        "outcomes",
        "settlements",
    )
}
PAYOUT_PROOF["payout_requests"] = ("request_id", "payout_protocol")
OBSERVATION = {
    P[n].name: tuple(P[n].c.keys())
    for n in ("requests", "intents", "outcomes", "commands")
}
LEGACY = {
    "legacy_financial_guards": ("user_id", "currency", "interaction_id"),
    "legacy_financial_cases": ("interaction_id", "released"),
    "interactions": (
        "interaction_id",
        "order_id",
        "blogger_id",
        "advertiser_id",
        "status",
    ),
    "orders": ("order_id", "currency"),
    "user_referral_bindings": ("referred_user_id", "referrer_user_id"),
    "referral_income_entries": ("order_id", "referrer_user_id", "currency"),
}
ITEMS = {
    "order_items": ("paid_item_id", "selection_state"),
    "financial_collaborations": tuple(
        m.Base.metadata.tables["financial_collaborations"].c.keys()
    ),
    "financial_collaboration_events": tuple(
        m.Base.metadata.tables["financial_collaboration_events"].c.keys()
    ),
}


OBSERVATION_SOURCES = (
    IDENTITY
    | AMOUNTS
    | REQUESTS
    | REQUIREMENTS
    | AUTHORITY
    | PAYOUT_PROOF
    | LEGACY
    | ITEMS
    | OBSERVATION
)
OBSERVATION_SOURCES["financial_obligations"] = tuple(
    m.Base.metadata.tables["financial_obligations"].c.keys()
)
OBSERVATION_SOURCES["users"] = tuple(m.UserModel.__table__.c.keys())


def _keyset(query, at, identity, cursor):
    return (
        query.where(
            sa.tuple_(at, identity) > (cursor.position, cursor.identity)
        )
        if cursor
        else query
    )


def _authority_join():
    request, state, event = P["requests"], P["states"], P["events"]
    latest = (
        sa.select(event)
        .where(event.c.request_id == request.c.request_id)
        .order_by(event.c.version.desc())
        .limit(1)
        .lateral("latest_payout_event")
    )
    joined = request.outerjoin(
        state, state.c.request_id == request.c.request_id
    ).outerjoin(latest, sa.true())
    proof = latest.c.details["projection"]
    expected = sa.func.jsonb_build_object(
        "request_id",
        sa.cast(request.c.request_id, sa.Text),
        "version",
        latest.c.version,
        "state",
        latest.c.state,
        "execution_id",
        sa.cast(state.c.execution_id, sa.Text),
        "block_reason",
        state.c.block_reason,
    )
    consistent = sa.func.coalesce(
        sa.and_(
            state.c.request_id.is_not(None),
            state.c.version == latest.c.version,
            state.c.state == latest.c.state,
            sa.func.jsonb_typeof(proof) == "object",
            proof == expected,
            proof["version"].as_string().op("~")(r"^[1-9][0-9]*$"),
        ),
        sa.false(),
    )
    return joined, consistent


def associated_event_query(request_id, execution_id):
    event = P["events"]
    proof = event.c.details["projection"]
    expected = sa.func.jsonb_build_object(
        "request_id",
        str(request_id),
        "version",
        event.c.version,
        "state",
        event.c.state,
        "execution_id",
        str(execution_id),
        "block_reason",
        proof["block_reason"].as_string(),
    )
    return (
        sa.select(event)
        .where(
            event.c.request_id == request_id,
            sa.func.jsonb_typeof(proof) == "object",
            proof == expected,
            proof["version"].as_string().op("~")(r"^[1-9][0-9]*$"),
            sa.func.jsonb_typeof(proof["block_reason"]) == "string",
            sa.func.char_length(proof["block_reason"].as_string()) <= 100,
        )
        .order_by(event.c.version.desc())
        .limit(1)
    )


def requests_query(
    recipient_id, page, cursor, *, queue, authority_available=True
):
    request = P["requests"]
    query = sa.select(request)
    if queue and authority_available:
        joined, consistent = _authority_join()
        state = P["states"]
        query = query.select_from(joined).where(
            sa.or_(
                ~consistent,
                state.c.state.not_in(("paid", "rejected")),
                state.c.block_reason != "",
            )
        )
    if recipient_id is not None:
        query = query.where(request.c.recipient_id == recipient_id)
    return (
        _keyset(query, request.c.requested_at, request.c.request_id, cursor)
        .order_by(request.c.requested_at, request.c.request_id)
        .limit(page.limit + 1)
    )


class SqlAlchemyPayoutViewRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    @asynccontextmanager
    async def snapshot(self):
        async with self.session_factory() as db:
            if db.get_bind().dialect.name != "postgresql":
                raise ValueError("payout_source_unavailable")
            async with db.begin():
                await db.execute(
                    sa.text(
                        "SET TRANSACTION ISOLATION LEVEL "
                        "REPEATABLE READ READ ONLY"
                    )
                )
                yield PayoutSnapshot(db)


class PayoutSnapshot:
    def __init__(self, session):
        self.session = session
        self.columns = None
        self.contracts = SqlAlchemyPayoutContractRepository()

    async def installed(self, family):
        if self.columns is None:
            rows = await self.session.execute(
                sa.text(
                    "SELECT c.relname,a.attname FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid "
                    "WHERE n.nspname=current_schema() "
                    "AND c.relkind IN ('r','p') AND a.attnum>0 "
                    "AND NOT a.attisdropped"
                )
            )
            self.columns = {}
            for table, column in rows:
                self.columns.setdefault(table, set()).add(column)
        return all(
            table in self.columns and set(columns) <= self.columns[table]
            for table, columns in family.items()
        )

    async def command_blockers(self, kind):
        sources = {
            "store": STORE_SOURCES,
            "publish": PUBLICATION_SOURCES,
            "review": MONEY_LOCK_SOURCES | REQUESTS,
        }[kind]
        return (
            ()
            if await self.installed(COMMAND_SOURCES | sources)
            else ("payout_source_unavailable",)
        )

    async def _rows(self, query):
        return tuple((await self.session.execute(query)).mappings())

    async def _one(self, query):
        return (await self.session.execute(query)).mappings().one_or_none()

    async def actor(self, principal):
        if not await self.installed(IDENTITY):
            raise ValueError("payout_source_unavailable")
        table = m.UserModel.__table__
        external = (
            table.c.telegram_id
            if principal.platform == "telegram"
            else table.c.max_id
        )
        row = await self._one(
            sa.select(
                table.c.user_id,
                external.label("native"),
                table.c.status,
                table.c.admin,
            ).where(
                table.c.user_id == principal.actor_id,
                external == principal.external_id,
            )
        )
        return (
            ReadActor(
                row["user_id"],
                principal.platform,
                row["native"],
                row["status"],
                row["admin"],
            )
            if row
            else None
        )

    async def _requirement(self, row):
        if row is None:
            return None
        contract = (
            await self.contracts.contract(row, session=self.session)
            if await self.installed(CONTRACTS)
            else None
        )
        return dict(row) | dict(
            document=contract["document"] if contract else None,
            field_definitions=contract["field_definitions"]
            if contract
            else None,
            readable=contract is not None,
        )

    async def requirements(self, at):
        if not await self.installed(REQUIREMENTS):
            return RequirementsRead(None, None, ("payout_source_unavailable",))
        table = P["requirements"]
        query = sa.select(table).order_by(table.c.version.desc()).limit(1)
        latest = await self._one(query)
        current = await self._one(query.where(table.c.effective_from <= at))
        return RequirementsRead(
            await self._requirement(current),
            await self._requirement(latest),
            (),
        )

    async def _requisite(self, row):
        table = P["requirements"]
        requirement = await self._one(
            sa.select(table).where(
                table.c.requirements_id == row["requirements_id"]
            )
        )
        row = dict(row) | {
            "requirements_version": requirement["version"]
            if requirement
            else None
        }
        contract = (
            await self.contracts.contract(requirement, session=self.session)
            if requirement and await self.installed(CONTRACTS)
            else None
        )
        acceptance = (
            await self.contracts.acceptance(
                row["requisites_id"], session=self.session
            )
            if contract
            else None
        )
        accepted = bool(
            acceptance
            and acceptance["accepted"] is True
            and (
                acceptance["recipient_id"],
                acceptance["requirements_id"],
                acceptance["document_id"],
                acceptance["sha256"],
            )
            == (
                row["recipient_id"],
                row["requirements_id"],
                contract["document"]["document_id"],
                contract["document"]["sha256"],
            )
        )
        return RequisiteRead(row, contract, accepted)

    async def requisites(self, recipient_id, page, cursor):
        if not await self.installed(
            {P["requisites"].name: tuple(P["requisites"].c.keys())}
            | REQUIREMENTS
        ):
            raise ValueError("payout_source_unavailable")
        table = P["requisites"]
        query = sa.select(table).where(table.c.recipient_id == recipient_id)
        rows = await self._rows(
            _keyset(query, table.c.recorded_at, table.c.requisites_id, cursor)
            .order_by(table.c.recorded_at, table.c.requisites_id)
            .limit(page.limit + 1)
        )
        return tuple([await self._requisite(row) for row in rows])

    async def requisite(self, recipient_id, requisites_id):
        if not await self.installed(
            {P["requisites"].name: tuple(P["requisites"].c.keys())}
            | REQUIREMENTS
        ):
            return None
        table = P["requisites"]
        row = await self._one(
            sa.select(table).where(
                table.c.recipient_id == recipient_id,
                table.c.requisites_id == requisites_id,
            )
        )
        return await self._requisite(row) if row else None

    async def _history_authority(self, recipient_id):
        """Money readiness only; preserve/read unproven foundation v1 facts.

        This is the nonlocking snapshot equivalent of the writer's guard.
        A balanced journal UUID alone is not bank/allocation authority.
        Ordinary legacy-only rows remain outside this v1 journal query.
        """
        movement = m.Base.metadata.tables["financial_movements"]
        obligation = m.Base.metadata.tables["financial_obligations"]
        anchor = m.PayoutRequestModel.__table__
        link, allocation, request, settlement, outcome, intent = (
            P[n]
            for n in (
                "movement_links",
                "allocations",
                "requests",
                "settlements",
                "outcomes",
                "intents",
            )
        )
        allocation_proof = (
            sa.select(link.c.movement_id)
            .select_from(
                link.join(
                    allocation,
                    allocation.c.allocation_id == link.c.allocation_id,
                )
                .join(request, request.c.request_id == link.c.request_id)
                .join(anchor, anchor.c.request_id == request.c.request_id)
            )
            .where(
                link.c.movement_id == movement.c.id,
                link.c.request_id == movement.c.request_id,
                link.c.allocation_id == movement.c.allocation_id,
                link.c.obligation_id == movement.c.obligation_id,
                link.c.currency == movement.c.currency,
                link.c.amount_minor == movement.c.amount_minor,
                link.c.execution_id.is_not_distinct_from(
                    movement.c.execution_id
                ),
                allocation.c.request_id == movement.c.request_id,
                allocation.c.obligation_id == movement.c.obligation_id,
                allocation.c.recipient_id == recipient_id,
                allocation.c.currency == movement.c.currency,
                allocation.c.amount_minor >= movement.c.amount_minor,
                request.c.recipient_id == recipient_id,
                request.c.currency == movement.c.currency,
                anchor.c.payout_protocol == "financial_v1",
            )
            .correlate(movement)
            .exists()
        )
        paid_proof = (
            sa.select(settlement.c.execution_id)
            .select_from(
                settlement.join(
                    outcome, outcome.c.outcome_id == settlement.c.outcome_id
                ).join(
                    intent, intent.c.execution_id == settlement.c.execution_id
                )
            )
            .where(
                settlement.c.execution_id == movement.c.execution_id,
                settlement.c.request_id == movement.c.request_id,
                settlement.c.currency == movement.c.currency,
                intent.c.request_id == movement.c.request_id,
                intent.c.amount_minor == settlement.c.amount_minor,
                intent.c.currency == movement.c.currency,
                outcome.c.execution_id == movement.c.execution_id,
                outcome.c.request_id == movement.c.request_id,
                outcome.c.applied.is_(True),
                outcome.c.status == "paid",
                outcome.c.amount_minor == settlement.c.amount_minor,
                outcome.c.currency == movement.c.currency,
                outcome.c.bank_account == settlement.c.bank_account,
                outcome.c.bank_reference == settlement.c.bank_reference,
                outcome.c.settled_at == settlement.c.settled_at,
                outcome.c.fingerprint == intent.c.fingerprint,
            )
            .correlate(movement)
            .exists()
        )
        missing = await self.session.scalar(
            sa.select(movement.c.id)
            .join(obligation, obligation.c.id == movement.c.obligation_id)
            .where(
                obligation.c.recipient_id == recipient_id,
                movement.c.currency == "RUB",
                sa.or_(
                    movement.c.bucket_from == "reserved",
                    movement.c.bucket_to.in_(("reserved", "paid")),
                ),
                sa.or_(
                    ~allocation_proof,
                    sa.and_(movement.c.bucket_to == "paid", ~paid_proof),
                ),
            )
            .limit(1)
        )
        if missing is not None:
            raise ValueError("payout_history_authority_review_required")

    async def _legacy_blocked(self, recipient_id):
        guard, case, interaction, order, binding, income = (
            m.Base.metadata.tables[n]
            for n in (
                "legacy_financial_guards",
                "legacy_financial_cases",
                "interactions",
                "orders",
                "user_referral_bindings",
                "referral_income_entries",
            )
        )
        released = (
            sa.select(case.c.interaction_id)
            .where(
                case.c.interaction_id == guard.c.interaction_id,
                case.c.released.is_(True),
            )
            .exists()
        )
        blocked = await self.session.scalar(
            sa.select(guard.c.interaction_id)
            .where(
                guard.c.user_id == recipient_id,
                guard.c.currency == "RUB",
                ~released,
            )
            .limit(1)
        )
        if blocked is not None:
            return True
        unreviewed = (
            ~sa.select(case.c.interaction_id)
            .where(
                case.c.interaction_id == interaction.c.interaction_id,
                case.c.released.is_(True),
            )
            .exists()
        )
        bindings = (
            sa.select(interaction.c.interaction_id)
            .join(order, order.c.order_id == interaction.c.order_id)
            .join(
                binding,
                sa.or_(
                    binding.c.referred_user_id == interaction.c.blogger_id,
                    binding.c.referred_user_id == interaction.c.advertiser_id,
                ),
            )
            .where(
                interaction.c.status == "issue",
                binding.c.referrer_user_id == recipient_id,
                order.c.currency == "RUB",
                unreviewed,
            )
        )
        historical = (
            sa.select(interaction.c.interaction_id)
            .join(
                income,
                sa.and_(
                    income.c.order_id == interaction.c.order_id,
                    income.c.referrer_user_id == recipient_id,
                    income.c.currency == "RUB",
                ),
            )
            .where(interaction.c.status == "issue", unreviewed)
        )
        return (
            await self.session.scalar(sa.union(bindings, historical).limit(1))
        ) is not None

    async def _unmatched_bank(self, recipient_id):
        outcome, request, settlement = (
            P["outcomes"],
            P["requests"],
            P["settlements"],
        )
        applied = outcome.alias("matched_applied")
        fields = (
            "execution_id",
            "request_id",
            "amount_minor",
            "currency",
            "settled_at",
            "bank_account",
            "bank_reference",
        )
        resolved = (
            sa.select(applied.c.outcome_id)
            .join(settlement, settlement.c.outcome_id == applied.c.outcome_id)
            .where(
                *(
                    applied.c[n].is_not_distinct_from(outcome.c[n])
                    for n in fields
                ),
                sa.or_(
                    outcome.c.key_id == "unavailable",
                    applied.c.fingerprint == outcome.c.fingerprint,
                ),
            )
            .correlate(outcome)
            .exists()
        )
        query = (
            sa.select(outcome.c.outcome_id)
            .join(request, request.c.request_id == outcome.c.request_id)
            .where(
                request.c.recipient_id == recipient_id,
                outcome.c.status == "paid",
                outcome.c.applied.is_(False),
                ~resolved,
            )
            .limit(1)
        )
        return (await self.session.scalar(query)) is not None

    async def _financial_readiness(self, recipient_id, empty):
        source, readiness = [], []
        if not await self.installed(COMMAND_SOURCES | MONEY_LOCK_SOURCES):
            readiness.append("payout_source_unavailable")
        if await self.installed(PAYOUT_PROOF):
            try:
                await self._history_authority(recipient_id)
            except ValueError as error:
                readiness.append(public_payout_code(error))
            if await self._unmatched_bank(recipient_id):
                readiness.append("payout_bank_reconciliation_required")
            if empty and await self.session.scalar(
                sa.select(P["requests"].c.request_id)
                .where(P["requests"].c.recipient_id == recipient_id)
                .limit(1)
            ):
                source.append("payout_source_integrity_required")
        else:
            readiness.append("payout_source_unavailable")
            if empty:
                source.append("payout_source_unavailable")
        if await self.installed(LEGACY):
            if await self._legacy_blocked(recipient_id):
                readiness.append("legacy_payout_blocked")
        else:
            readiness.append("payout_source_unavailable")
        return source, readiness

    async def financial(self, recipient_id):
        if not await self.installed(AMOUNTS):
            return FinancialRead(
                (), (), None, ("payout_source_unavailable",), (), None
            )
        obligation, movement, wallet = (
            m.Base.metadata.tables[n]
            for n in (
                "financial_obligations",
                "financial_movements",
                "financial_wallets",
            )
        )
        raw = await self._rows(
            sa.select(
                obligation.c.id,
                obligation.c.recipient_id,
                obligation.c.currency,
                obligation.c.amount_minor,
                obligation.c.paid_item_id,
            ).where(obligation.c.recipient_id == recipient_id)
        )
        entries = await self._rows(
            sa.select(movement)
            .join(obligation, obligation.c.id == movement.c.obligation_id)
            .where(obligation.c.recipient_id == recipient_id)
            .order_by(movement.c.append_order)
        )
        projection = await self._one(
            sa.select(wallet).where(
                wallet.c.recipient_id == recipient_id,
                wallet.c.currency == "RUB",
            )
        )
        source = []
        # An unscoped orphan is a global integrity stop, never attributed to
        # the movement's actor or exposed as a different owner's history.
        orphan = await self.session.scalar(
            sa.select(movement.c.id)
            .outerjoin(obligation, obligation.c.id == movement.c.obligation_id)
            .where(obligation.c.id.is_(None))
            .limit(1)
        )
        if orphan is not None:
            source.append("payout_source_integrity_required")
        try:
            obligations = tuple(
                ReadObligation(
                    ObligationBasis(
                        r["id"],
                        r["recipient_id"],
                        r["currency"],
                        r["amount_minor"],
                    ),
                    r["paid_item_id"],
                )
                for r in raw
            )
            movements = tuple(
                JournalMovement(
                    **{f.name: r[f.name] for f in fields(JournalMovement)}
                )
                for r in entries
            )
        except (ValueError, TypeError, KeyError):
            obligations, movements = (), ()
            source.append("payout_source_integrity_required")
        extra, readiness = await self._financial_readiness(
            recipient_id, not raw and not entries and projection is None
        )
        source += extra
        status = await self.session.scalar(
            sa.select(m.UserModel.status).where(
                m.UserModel.user_id == recipient_id
            )
        )
        return FinancialRead(
            obligations,
            movements,
            {b: projection[b + "_minor"] for b in BUCKETS}
            if projection
            else None,
            tuple(source),
            tuple(readiness),
            status,
        )

    async def item_blockers(self, item_ids):
        if not await self.installed(ITEMS):
            return ("payout_source_unavailable",)
        table = m.Base.metadata.tables["order_items"]
        rows = await self._rows(
            sa.select(table.c.paid_item_id, table.c.selection_state).where(
                table.c.paid_item_id.in_(item_ids)
            )
        )
        if {r["paid_item_id"] for r in rows} != set(item_ids) or any(
            r["selection_state"] in ("cancelled", "refunded") for r in rows
        ):
            return ("payout_item_corrected_review_required",)
        repo = SqlAlchemyWorkEntitlementRepository()
        try:
            for item in item_ids:
                if (
                    await repo.get_dispute_case(item, session=self.session)
                    is not None
                ):
                    return ("work_disputed",)
        except (ValueError, TypeError, KeyError):
            return ("payout_source_integrity_required",)
        return ()

    async def _authority(self, request_id):
        if not await self.installed(AUTHORITY):
            return None, False
        raw = await self._one(
            sa.select(P["states"]).where(P["states"].c.request_id == request_id)
        )
        event = await self._one(
            sa.select(P["events"])
            .where(P["events"].c.request_id == request_id)
            .order_by(P["events"].c.version.desc())
            .limit(1)
        )
        proof = self._event_proof(event, request_id)
        if proof is None:
            return None, False
        comparable = (
            {
                k: str(v) if isinstance(v, UUID) else v
                for k, v in dict(raw).items()
            }
            if raw
            else None
        )
        expected = {
            k: str(v) if isinstance(v, UUID) else v for k, v in proof.items()
        }
        return proof, comparable == expected

    @staticmethod
    def _event_proof(event, request_id):
        details = event.get("details") if event else None
        value = details.get("projection") if isinstance(details, dict) else None
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "request_id",
                "version",
                "state",
                "execution_id",
                "block_reason",
            }
            or type(value.get("version")) is not int
            or value["version"] != event["version"]
            or value["state"] != event["state"]
            or value["request_id"] != str(request_id)
            or not isinstance(value["block_reason"], str)
            or len(value["block_reason"]) > 100
        ):
            return None
        try:
            return value | {
                "request_id": UUID(value["request_id"]),
                "execution_id": UUID(value["execution_id"])
                if value["execution_id"] is not None
                else None,
            }
        except (ValueError, TypeError, AttributeError):
            return None

    async def _intent(self, row, request_id):
        version = None
        if await self.installed(AUTHORITY):
            # This event is tied to this execution, not inferred from an
            # unrelated maximum time or mutable state/paged subset.
            candidates = await self._rows(
                associated_event_query(request_id, row["execution_id"])
            )
            proof = (
                self._event_proof(candidates[0], request_id)
                if candidates
                else None
            )
            version = proof["version"] if proof else None
        return dict(row) | dict(
            version=version,
            version_provenance="retained_event"
            if version is not None
            else "retained_version_required",
        )

    async def _request(self, row):
        request_id = row["request_id"]
        authority, consistent = await self._authority(request_id)
        requisite = await self.requisite(
            row["recipient_id"], row["requisites_id"]
        )
        source = []
        if requisite is None:
            source.append("payout_requisites_unavailable")
            consistent = False
        allocations = []
        if await self.installed(
            {P["allocations"].name: tuple(P["allocations"].c.keys())}
            | {"financial_obligations": AMOUNTS["financial_obligations"]}
        ):
            table, obligation = (
                P["allocations"],
                m.Base.metadata.tables["financial_obligations"],
            )
            rows = await self._rows(
                sa.select(
                    table,
                    obligation.c.paid_item_id,
                    obligation.c.recipient_id.label("actual_owner"),
                )
                .outerjoin(obligation, obligation.c.id == table.c.obligation_id)
                .where(table.c.request_id == request_id)
                .order_by(table.c.obligation_id)
            )
            for allocation in rows:
                if (
                    allocation["paid_item_id"] is None
                    or allocation["actual_owner"] != row["recipient_id"]
                    or allocation["recipient_id"] != row["recipient_id"]
                    or allocation["currency"] != row["currency"]
                ):
                    source.append("payout_allocation_source_unavailable")
                else:
                    allocations.append(
                        ReadAllocation(
                            allocation["obligation_id"],
                            allocation["paid_item_id"],
                            allocation["amount_minor"],
                        )
                    )
        else:
            source.append("payout_allocation_source_unavailable")
        retained = []
        current = None
        intent = P["intents"]
        if await self.installed({intent.name: tuple(intent.c.keys())}):
            rows = await self._rows(
                sa.select(intent)
                .where(intent.c.request_id == request_id)
                .order_by(intent.c.prepared_at, intent.c.execution_id)
                .limit(21)
            )
            retained = [await self._intent(r, request_id) for r in rows[:20]]
            if consistent and authority and authority["execution_id"]:
                selected = await self._one(
                    sa.select(intent).where(
                        intent.c.execution_id == authority["execution_id"],
                        intent.c.request_id == request_id,
                    )
                )
                current = (
                    await self._intent(selected, request_id)
                    if selected
                    else None
                )
        else:
            rows = ()
        escalated = False
        if await self.installed(AUTHORITY):
            event = P["events"]
            escalated = (
                await self.session.scalar(
                    sa.select(event.c.event_id)
                    .where(
                        event.c.request_id == request_id,
                        event.c.action == "escalate",
                    )
                    .limit(1)
                )
            ) is not None
        physical_sources = await self.installed(OBSERVATION_SOURCES)
        observation = bool(retained) and physical_sources
        return RequestRead(
            dict(row),
            authority,
            consistent,
            requisite,
            tuple(allocations),
            current,
            tuple(retained),
            len(rows) > 20,
            escalated,
            tuple(source),
            observation,
            ()
            if physical_sources
            else ("payout_observation_source_unavailable",),
        )

    async def request(self, request_id, recipient_id):
        if not await self.installed(
            {P["requests"].name: tuple(P["requests"].c.keys())}
        ):
            raise ValueError("payout_source_unavailable")
        table = P["requests"]
        query = sa.select(table).where(table.c.request_id == request_id)
        if recipient_id is not None:
            query = query.where(table.c.recipient_id == recipient_id)
        row = await self._one(query)
        return await self._request(row) if row else None

    async def requests(self, recipient_id, page, cursor, *, queue):
        if not await self.installed(
            {P["requests"].name: tuple(P["requests"].c.keys())}
        ):
            raise ValueError("payout_source_unavailable")
        rows = await self._rows(
            requests_query(
                recipient_id,
                page,
                cursor,
                queue=queue,
                authority_available=await self.installed(AUTHORITY | REQUESTS),
            )
        )
        return tuple([await self._request(row) for row in rows])

    async def requirements_page(self, page, cursor):
        if not await self.installed(REQUIREMENTS):
            raise ValueError("payout_source_unavailable")
        table = P["requirements"]
        rows = await self._rows(
            _keyset(
                sa.select(table),
                table.c.recorded_at,
                table.c.requirements_id,
                cursor,
            )
            .order_by(table.c.recorded_at, table.c.requirements_id)
            .limit(page.limit + 1)
        )
        return tuple([await self._requirement(row) for row in rows])

    async def history(self, request_id, kind, page, cursor):
        table = P[kind]
        if not await self.installed({table.name: tuple(table.c.keys())}):
            raise ValueError("payout_source_unavailable")
        position, identity = {
            "events": ("version", "event_id"),
            "intents": ("prepared_at", "execution_id"),
            "outcomes": ("recorded_at", "outcome_id"),
            "settlements": ("settled_at", "execution_id"),
        }[kind]
        query = (
            _keyset(
                sa.select(table).where(table.c.request_id == request_id),
                table.c[position],
                table.c[identity],
                cursor,
            )
            .order_by(table.c[position], table.c[identity])
            .limit(page.limit + 1)
        )
        rows = await self._rows(query)
        return (
            tuple([await self._intent(row, request_id) for row in rows])
            if kind == "intents"
            else rows
        )
