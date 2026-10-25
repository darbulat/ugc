"""Publish environment rules without activating financial flows."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
)
from ugc_bot.config import FinancialConfig
from ugc_bot.domain.financial import utc
from ugc_bot.domain.refund_rules import RefundRules


@dataclass(frozen=True, slots=True)
class FinancialPolicyDraft:
    version: str
    effective_from: datetime
    allowed_clients: frozenset[UUID]
    terms_reference: str
    refund_rules: RefundRules

    def __post_init__(self) -> None:
        for value, limit in ((self.version, 64), (self.terms_reference, 2048)):
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
                or len(value) > limit
            ):
                raise ValueError("policy_identity_and_terms_required")
        object.__setattr__(self, "effective_from", utc(self.effective_from))
        clients = frozenset(self.allowed_clients)
        if not clients or any(
            not isinstance(client, UUID) or client.int == 0
            for client in clients
        ):
            raise ValueError("policy_allowed_clients_required")
        object.__setattr__(self, "allowed_clients", clients)
        if not isinstance(self.refund_rules, RefundRules):
            raise ValueError("refund_rules_required")

    @classmethod
    def from_environment(
        cls,
        config: FinancialConfig,
        *,
        version: str,
        effective_from: datetime,
        allowed_clients: frozenset[UUID],
        terms_reference: str,
    ) -> "FinancialPolicyDraft":
        rules = config.refund_rules()
        if rules is None:
            raise ValueError("refund_rules_required")
        return cls(
            version, effective_from, allowed_clients, terms_reference, rules
        )

    def to_document(self) -> dict:
        return {
            "version": self.version,
            "effective_from": self.effective_from.isoformat(),
            "allowed_clients": sorted(str(c) for c in self.allowed_clients),
            "terms_reference": self.terms_reference,
            "refund_window_seconds": (
                self.refund_rules.selection_refund_window_seconds
            ),
            "refund_rules": self.refund_rules.to_document(),
        }


class FinancialPolicyPublicationRepository(Protocol):
    async def lock_active_admin(
        self, actor_id: UUID, *, session: object
    ) -> bool: ...

    async def lock_version(self, version: str, *, session: object) -> None: ...

    async def load(
        self, version: str, *, session: object
    ) -> FinancialPolicy | None: ...

    async def save_approved(
        self, policy: FinancialPolicy, *, session: object
    ) -> None: ...


@dataclass
class FinancialPolicyPublicationService:
    repository: FinancialPolicyPublicationRepository
    transactions: TransactionManager
    clock: Clock

    async def publish(
        self, draft: FinancialPolicyDraft, *, actor_id: UUID
    ) -> FinancialPolicy:
        if not isinstance(actor_id, UUID) or actor_id.int == 0:
            raise PermissionError("active_admin_required")
        if not isinstance(draft, FinancialPolicyDraft):
            raise ValueError("policy_draft_required")
        async with self.transactions.transaction() as session:
            repo = self.repository
            if not await repo.lock_active_admin(actor_id, session=session):
                raise PermissionError("active_admin_required")
            await repo.lock_version(draft.version, session=session)
            existing = await repo.load(draft.version, session=session)
            if existing is not None:
                if not self._matches(existing, draft, actor_id):
                    raise ValueError("policy_version_conflict")
                return existing
            now = utc(self.clock.now())
            if draft.effective_from < now:
                raise ValueError("approval_after_activation")
            policy = FinancialPolicy(
                version=draft.version,
                approved_by=actor_id,
                approved_at=now,
                effective_from=draft.effective_from,
                selection_refund_window=timedelta(
                    seconds=draft.refund_rules.selection_refund_window_seconds
                ),
                allowed_clients=draft.allowed_clients,
                terms_reference=draft.terms_reference,
                refund_rules=draft.refund_rules,
            )
            await repo.save_approved(policy, session=session)
            return policy

    @staticmethod
    def _matches(policy, draft, actor_id) -> bool:
        return (
            policy.approved_by == actor_id
            and policy.approved_at is not None
            and policy.effective_from == draft.effective_from
            and policy.allowed_clients == draft.allowed_clients
            and policy.terms_reference == draft.terms_reference
            and policy.refund_rules == draft.refund_rules
        )
