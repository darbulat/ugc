"""Declared synthetic command facts; no SQL, provider or runtime authority."""

from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.application.correction_ports import (
    CorrectionScope,
    RequestSelectionRefund,
    correction_command_hash,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.physical_proof_ports import (
    PhysicalProofConflict,
    PhysicalProofIdentity,
    PhysicalProofUnavailable,
)
from ugc_bot.domain.corrections import (
    CapturedSelectionComponent,
    SelectionRefundBundle,
)

U = tuple(UUID(int=i) for i in range(1, 31))
NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
HASH = "a" * 64


class Proofs:
    def __init__(self):
        self.rows = {}
        self.available = True

    def resolve_manual_identity(self, account, reference, *, direction):
        if not self.available or account != "synthetic-bank":
            raise PhysicalProofUnavailable()
        return PhysicalProofIdentity(
            source="synthetic-source",
            account=account,
            reference=reference,
            direction=direction,
        )

    async def claim(self, identity, owner, *, session):
        old = self.rows.get(identity.key)
        if old and (old.producer, old.intent_id) != (
            owner.producer,
            owner.intent_id,
        ):
            raise PhysicalProofConflict()
        self.rows.setdefault(identity.key, owner)
        return self.rows[identity.key]

    async def owners(self, identity, *, session):
        return (self.rows[identity.key],) if identity.key in self.rows else ()


class Repository:
    def __init__(self):
        component = CapturedSelectionComponent(
            allocation_key="synthetic:selection",
            payment_id=U[6],
            paid_item_id=U[5],
            gross_minor=50000,
            currency="RUB",
            selection_due_at=NOW - timedelta(days=1),
            due_evidence_hash=HASH,
        )
        self.scope = CorrectionScope(
            actor_id=U[0],
            prospective_user_ids=(U[0], U[1], U[2]),
            wallet_user_ids=(U[2],),
            source_hash=HASH,
            order_id=U[3],
            client_id=U[0],
            intent_id=U[4],
            capture_id=U[7],
            payment_id=U[6],
            captured_at=NOW - timedelta(days=2),
            quote_key="synthetic:quote",
            terms_reference="synthetic:terms",
            bundle=SelectionRefundBundle(components=(component,)),
            selected_paid_item_ids=(U[5],),
        )
        self.captured = self.scope
        self.trace = []
        self.rows = {
            name: []
            for name in (
                "cases",
                "requests",
                "intents",
                "observations",
                "matches",
                "approvals",
                "match_approvals",
                "commands",
            )
        }
        self.events = []
        self.actors = {
            U[0]: dict(
                user_id=U[0],
                telegram_id="101",
                max_id="201",
                status="active",
                admin=False,
            ),
            U[1]: dict(
                user_id=U[1],
                telegram_id="102",
                max_id="202",
                status="active",
                admin=True,
            ),
            U[2]: dict(
                user_id=U[2],
                telegram_id="103",
                max_id="203",
                status="active",
                admin=False,
            ),
        }
        self.session = object()
        self.consistent = True
        self.changed = False
        self.refusal = None

    async def discover_scope(self, command, *, session):
        self.trace.append("discover")
        case = getattr(command, "existing_case_id", None) or getattr(
            command, "case_id", None
        )
        return replace(self.scope, actor_id=command.actor_id, case_id=case)

    async def discover_case_scope(self, actor_id, case_id, *, session):
        return replace(self.scope, actor_id=actor_id, case_id=case_id)

    async def discover_operation_scope(
        self, actor_id, operation_key, *, session
    ):
        row = next(
            (
                r
                for r in self.rows["commands"]
                if r["actor_id"] == actor_id
                and r["operation_key"] == operation_key
            ),
            None,
        )
        case = UUID(row["result"]["case_id"]) if row else None
        return await self.discover_case_scope(actor_id, case, session=session)

    async def prepare_users(self, scope, *, session):
        assert session is self.session
        self.trace.append("barrier")
        self.trace.append(("users", tuple(sorted(scope.prospective_user_ids))))

    async def lock_scope(self, scope, *, session):
        await self.prepare_users(scope, session=session)
        await self.lock_prepared_scope(scope, session=session)

    async def lock_prepared_scope(self, scope, *, session):
        assert session is self.session
        assert (
            "users",
            tuple(sorted(scope.prospective_user_ids)),
        ) in self.trace
        self.trace.append("wallets")
        if self.changed:
            raise ValueError("correction_scope_changed_retry_required")

    async def read_authority(self, scope, *, operation_key=None, session):
        from ugc_bot.application.correction_ports import CorrectionReadAuthority

        self.trace.append("read_authority")
        bindings, action = {}, None
        for kind, prefix in (("requests", "request"), ("cases", "case")):
            rows = [r for r in self.rows[kind] if r["case_id"] == scope.case_id]
            if rows:
                bindings.update(
                    {
                        f"{prefix}_{key}": rows[0][key]
                        for key in ("client_id", "order_id")
                    }
                )
        if operation_key is not None:
            rows = [
                r
                for r in self.rows["commands"]
                if r["actor_id"] == scope.actor_id
                and r["operation_key"] == operation_key
            ]
            action = rows[0]["action"] if rows else None
        return CorrectionReadAuthority(
            current_client_id=self.scope.client_id,
            action=action,
            **bindings,
        )

    async def load_scope(self, scope, *, session):
        self.trace.append("reread")
        return scope

    async def actor(self, actor_id, *, session):
        from ugc_bot.application.correction_ports import CorrectionActor

        self.trace.append("actor")
        row = self.actors.get(actor_id)
        return CorrectionActor(**row) if row else None

    async def facts(self, scope, *, session):
        from ugc_bot.application.correction_ports import (
            CorrectionFact,
            CorrectionFacts,
        )

        self.trace.append("facts")
        values = [
            CorrectionFact.from_values(name, row)
            for name, rows in self.rows.items()
            for row in rows
            if name == "commands"
            or row.get("case_id") == scope.case_id
            or (
                name == "match_approvals"
                and row["match_id"]
                in {
                    match["match_id"]
                    for match in self.rows["matches"]
                    if match["case_id"] == scope.case_id
                }
            )
        ]
        values += [
            CorrectionFact.from_values("events", asdict(e))
            for e in self.events
            if e.case_id == scope.case_id
        ]
        if scope.payment_id:
            values += [
                CorrectionFact.from_values(
                    "payments",
                    dict(
                        payment_id=scope.payment_id,
                        order_id=scope.order_id,
                        provider="synthetic-provider",
                        status="paid",
                        external_id="synthetic-payment",
                        currency="RUB",
                    ),
                )
            ]
            values += [
                CorrectionFact.from_values(
                    "invoice",
                    dict(
                        event_id=scope.intent_id,
                        event_type="financial.capture_intent",
                        payload=dict(
                            account="synthetic-original-account",
                            provider="synthetic-provider",
                        ),
                    ),
                )
            ]
        return CorrectionFacts(records=tuple(values))

    async def state_authority(self, case_id, *, session):
        rows = [e for e in self.events if e.case_id == case_id]
        return (rows[-1].result_state if rows else None), self.consistent

    async def command(self, actor_id, operation_key, *, session):
        self.trace.append("receipt")
        return next(
            (
                r
                for r in self.rows["commands"]
                if r["actor_id"] == actor_id
                and r["operation_key"] == operation_key
            ),
            None,
        )

    async def save_command(self, command, payload_hash, result, *, session):
        from ugc_bot.application.correction_ports import correction_command_id

        assert payload_hash == correction_command_hash(command)
        self.rows["commands"].append(
            dict(
                command_id=correction_command_id(command),
                actor_id=command.actor_id,
                operation_key=command.operation_key,
                action=type(command).__name__,
                result=canonical(result),
                payload_hash=payload_hash,
            )
        )

    async def append_fact(self, name, values, *, session):
        assert session is self.session
        if name == "matches" and self.refusal:
            raise self.refusal
        self.rows[name].append(deepcopy(values))

    async def append_event(self, event, *, session):
        self.events.append(event)

    @asynccontextmanager
    async def application_savepoint(self, *, session):
        self.trace.append("savepoint")
        before = deepcopy(self.rows)
        try:
            yield session
        except BaseException:
            self.rows = before
            raise


def environment():
    from ugc_bot.application.services.correction_service import (
        CorrectionService,
    )

    repo, proofs = Repository(), Proofs()
    service = CorrectionService(repo, proofs, SimpleNamespace(now=lambda: NOW))

    async def execute(command, *, principal=None):
        principal = principal or AuthenticatedMessengerPrincipal(
            command.actor_id,
            "telegram",
            repo.actors[command.actor_id]["telegram_id"],
        )
        return await service.execute(
            command, principal=principal, session=repo.session
        )

    return SimpleNamespace(
        repo=repo, proofs=proofs, service=service, execute=execute
    )


def request(**changes):
    return RequestSelectionRefund(
        **(
            dict(
                actor_id=U[0],
                operation_key="request",
                reason="Synthetic agreed due passed",
                order_id=U[3],
                paid_item_ids=(U[5],),
                expected_source_hash=HASH,
            )
            | changes
        )
    )
