"""Dormant shared physical-proof adapter; no producer is installed here.

Historical attribution is independent of money eligibility. Pure classifiers
accept declared fact rows; only the adapter reads SQL in the caller transaction.
"""

from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.physical_proof_ports import (
    PhysicalProofConflict,
    PhysicalProofIdentity,
    PhysicalProofOwner,
    PhysicalProofUnavailable,
)
from ugc_bot.domain.corrections import require_text
from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.db import models as m

Row = Mapping[str, Any]
PROOFS = m.Base.metadata.tables["financial_physical_proof_claims"]
PAYOUT = {
    name: m.Base.metadata.tables["financial_payout_" + name]
    for name in ("outcomes", "settlements", "intents", "commands", "events")
}


def _require(value: bool) -> None:
    if not value:
        raise PhysicalProofUnavailable()


def _normalized(value: Any, limit: int) -> str:
    try:
        require_text(value, limit)
    except ValueError:
        raise PhysicalProofUnavailable() from None
    return cast(str, value).strip()


def _uuid(row: Row, key: str) -> UUID:
    value = row.get(key)
    _require(isinstance(value, UUID) and bool(value.int))
    return cast(UUID, value)


def _key_hash(identity: PhysicalProofIdentity) -> str:
    return sha256(identity.key.encode("utf-8")).hexdigest()


def _economic_owner(owner: PhysicalProofOwner) -> tuple[str, UUID]:
    return owner.producer, owner.intent_id


def _merge_owners(
    claims: Sequence[PhysicalProofOwner], history: Sequence[PhysicalProofOwner]
) -> tuple[PhysicalProofOwner, ...]:
    owners: dict[tuple[str, UUID], PhysicalProofOwner] = {}
    for owner in (
        *claims,
        *sorted(
            history, key=lambda x: (str(x.observation_id), str(x.command_id))
        ),
    ):
        owners.setdefault(_economic_owner(owner), owner)
    return tuple(
        owners[key] for key in sorted(owners, key=lambda x: (x[0], str(x[1])))
    )


def _existing_owner(
    owners: Sequence[PhysicalProofOwner], new: PhysicalProofOwner
) -> PhysicalProofOwner | None:
    if any(_economic_owner(old) != _economic_owner(new) for old in owners):
        raise PhysicalProofConflict()
    return owners[0] if owners else None


def _claim_row_owner(
    identity: PhysicalProofIdentity, row: Row
) -> PhysicalProofOwner:
    _uuid(row, "claim_id")
    _require(row.get("key_hash") == _key_hash(identity))
    _require(
        all(
            row.get(key) == getattr(identity, key)
            for key in ("source", "account", "direction", "reference")
        )
    )
    try:
        return PhysicalProofOwner(
            producer=cast(
                Literal["payout", "refund", "repayment"], row.get("producer")
            ),
            intent_id=_uuid(row, "intent_id"),
            observation_id=_uuid(row, "observation_id"),
            command_id=_uuid(row, "command_id"),
        )
    except ValueError:
        raise PhysicalProofUnavailable() from None


def _command_for_outcome(
    outcome: Row, commands: Sequence[Row], events: Sequence[Row]
) -> UUID:
    outcome_id, request, actor = (
        _uuid(outcome, key) for key in ("outcome_id", "request_id", "actor_id")
    )
    linked = [
        row
        for row in events
        if type(row.get("details")) is dict
        and row["details"].get("outcome_id") == str(outcome_id)
    ]
    _require(len(linked) <= 1)
    for event in linked:
        _require(
            event.get("action") == "bank_result"
            and _uuid(event, "request_id") == request
            and _uuid(event, "actor_id") == actor
        )
        _require(type(event.get("version")) is int and event["version"] > 0)
    found = []
    for command in commands:
        result = command.get("result")
        if type(result) is not dict:
            continue
        direct = type(result.get("outcome_id")) is str and result[
            "outcome_id"
        ] == str(outcome_id)
        ordinary = (
            command.get("action") == "RecordPayoutResult"
            and "outcome_id" not in result
            and bool(linked)
            and type(result.get("version")) is int
            and result["version"] == linked[0]["version"]
            and result.get("request_id") == str(request)
        )
        if not direct and not ordinary:
            continue
        _require(
            command.get("action") == "RecordPayoutResult"
            and _uuid(command, "actor_id") == actor
        )
        _require(
            type(result.get("request_id")) is str
            and result["request_id"] == str(request)
        )
        version = result.get("version")
        _require(
            (direct and version is None)
            or (type(version) is int and version > 0)
        )
        _require("outcome_id" not in result or direct)
        found.append(_uuid(command, "command_id"))
    _require(len(found) == 1)
    return found[0]


def _caller(session: object) -> AsyncSession:
    if (
        not isinstance(session, AsyncSession)
        or not session.in_transaction()
        or getattr(session, "bind", None) is None
        or session.bind.dialect.name != "postgresql"
    ):
        raise PhysicalProofUnavailable()
    return session


async def _rows(db: AsyncSession, statement: Any) -> Sequence[Row]:
    return cast(Sequence[Row], (await db.execute(statement)).mappings().all())


class SqlAlchemyPhysicalProofRepository:
    def __init__(self, source_id: str, canonical_account_id: str, clock: Clock):
        self.source_id = source_id
        self.canonical_account_id = canonical_account_id
        self.clock = clock

    def resolve_manual_identity(
        self,
        bank_account_label: str,
        reference: str,
        *,
        direction: Literal["incoming", "outgoing"],
    ) -> PhysicalProofIdentity:
        source = _normalized(self.source_id, 256)
        account = _normalized(self.canonical_account_id, 256)
        _require(_normalized(bank_account_label, 256) == account)
        try:
            return PhysicalProofIdentity(
                source=source,
                account=account,
                direction=direction,
                reference=_normalized(reference, 4000),
            )
        except ValueError:
            raise PhysicalProofUnavailable() from None

    def _identity(self, identity: PhysicalProofIdentity) -> None:
        _require(isinstance(identity, PhysicalProofIdentity))
        _require(
            identity
            == self.resolve_manual_identity(
                identity.account,
                identity.reference,
                direction=identity.direction,
            )
        )

    def _observed_identity(self, row: Row) -> PhysicalProofIdentity:
        return self.resolve_manual_identity(
            _normalized(row.get("bank_account"), 256),
            _normalized(row.get("bank_reference"), 4000),
            direction="outgoing",
        )

    def _historical_owners(
        self,
        identity: PhysicalProofIdentity,
        *,
        outcomes: Sequence[Row],
        settlements: Sequence[Row],
        intents: Sequence[Row],
        commands: Sequence[Row],
        events: Sequence[Row],
    ) -> tuple[PhysicalProofOwner, ...]:
        self._identity(identity)
        if identity.direction != "outgoing":
            return ()
        paid = [
            row
            for row in outcomes
            if row.get("status") == "paid"
            and isinstance(row.get("bank_reference"), str)
            and row["bank_reference"].strip() == identity.reference
        ]
        for settlement in settlements:
            if (
                not isinstance(settlement.get("bank_reference"), str)
                or settlement["bank_reference"].strip() != identity.reference
            ):
                continue
            _require(self._observed_identity(settlement) == identity)
            associated = [
                row
                for row in outcomes
                if row.get("outcome_id") == _uuid(settlement, "outcome_id")
            ]
            _require(len(associated) == 1)
            observed = associated[0]
            _require(
                observed.get("status") == "paid"
                and _uuid(observed, "execution_id")
                == _uuid(settlement, "execution_id")
                and _uuid(observed, "request_id")
                == _uuid(settlement, "request_id")
            )
            _require(self._observed_identity(observed) == identity)
        owners = []
        for outcome in paid:
            _require(self._observed_identity(outcome) == identity)
            execution = _uuid(outcome, "execution_id")
            associated = [
                row for row in intents if row.get("execution_id") == execution
            ]
            _require(
                len(associated) == 1
                and _uuid(associated[0], "request_id")
                == _uuid(outcome, "request_id")
            )
            owners.append(
                PhysicalProofOwner(
                    producer="payout",
                    intent_id=execution,
                    observation_id=_uuid(outcome, "outcome_id"),
                    command_id=_command_for_outcome(outcome, commands, events),
                )
            )
        return _merge_owners((), owners)

    async def lock(
        self, identity: PhysicalProofIdentity, *, session: object
    ) -> None:
        self._identity(identity)
        db = _caller(session)
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:proof, 0))"),
            {"proof": "ugc:physical-proof:" + identity.key},
        )

    async def owners(
        self, identity: PhysicalProofIdentity, *, session: object
    ) -> tuple[PhysicalProofOwner, ...]:
        await self.lock(identity, session=session)
        return await self._owners(identity, _caller(session))

    async def _owners(
        self, identity: PhysicalProofIdentity, db: AsyncSession
    ) -> tuple[PhysicalProofOwner, ...]:
        claims = await _rows(
            db, select(PROOFS).where(PROOFS.c.key_hash == _key_hash(identity))
        )
        _require(len(claims) <= 1)
        retained = tuple(_claim_row_owner(identity, row) for row in claims)
        if identity.direction != "outgoing":
            return retained
        outcome, settlement = PAYOUT["outcomes"], PAYOUT["settlements"]
        observed = list(
            await _rows(
                db,
                select(outcome).where(
                    outcome.c.status == "paid",
                    func.trim(outcome.c.bank_reference) == identity.reference,
                ),
            )
        )
        settled = await _rows(
            db,
            select(settlement).where(
                func.trim(settlement.c.bank_reference) == identity.reference
            ),
        )
        missing = {row["outcome_id"] for row in settled} - {
            row["outcome_id"] for row in observed
        }
        if missing:
            observed.extend(
                await _rows(
                    db, select(outcome).where(outcome.c.outcome_id.in_(missing))
                )
            )
        if not observed and not settled:
            return retained
        executions = {row["execution_id"] for row in (*observed, *settled)}
        requests = {str(row["request_id"]) for row in (*observed, *settled)}
        outcome_ids = {str(row["outcome_id"]) for row in (*observed, *settled)}
        intent, command, event = (
            PAYOUT[name] for name in ("intents", "commands", "events")
        )
        intents = await _rows(
            db, select(intent).where(intent.c.execution_id.in_(executions))
        )
        commands = await _rows(
            db,
            select(command).where(
                or_(
                    command.c.result["request_id"].as_string().in_(requests),
                    command.c.result["outcome_id"].as_string().in_(outcome_ids),
                )
            ),
        )
        events = await _rows(
            db,
            select(event).where(
                or_(
                    event.c.request_id.in_(
                        {row["request_id"] for row in (*observed, *settled)}
                    ),
                    event.c.details["outcome_id"].as_string().in_(outcome_ids),
                )
            ),
        )
        historical = self._historical_owners(
            identity,
            outcomes=observed,
            settlements=settled,
            intents=intents,
            commands=commands,
            events=events,
        )
        return _merge_owners(retained, historical)

    async def claim(
        self,
        identity: PhysicalProofIdentity,
        owner: PhysicalProofOwner,
        *,
        session: object,
    ) -> PhysicalProofOwner:
        """Retain real preallocated IDs before the producer inserts its outcome.

        The producer owns the same outer command/outcome transaction and must
        call here outside its economic savepoint. No future row is required.
        """
        _require(isinstance(owner, PhysicalProofOwner))
        await self.lock(identity, session=session)
        db = _caller(session)
        existing = _existing_owner(await self._owners(identity, db), owner)
        if existing is not None:
            return existing
        inserted = await db.scalar(
            insert(PROOFS)
            .values(
                claim_id=uuid4(),
                source=identity.source,
                account=identity.account,
                direction=identity.direction,
                reference=identity.reference,
                key_hash=_key_hash(identity),
                producer=owner.producer,
                intent_id=owner.intent_id,
                observation_id=owner.observation_id,
                command_id=owner.command_id,
                recorded_at=utc(self.clock.now()),
            )
            .on_conflict_do_nothing(index_elements=[PROOFS.c.key_hash])
            .returning(PROOFS.c.claim_id)
        )
        if inserted is not None:
            return owner
        existing = _existing_owner(await self._owners(identity, db), owner)
        if existing is None:
            raise PhysicalProofUnavailable()
        return existing
