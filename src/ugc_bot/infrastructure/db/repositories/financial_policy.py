"""Immutable approved policy persistence in the caller's transaction."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
)
from ugc_bot.domain.enums import UserStatus
from ugc_bot.domain.refund_rules import RefundRules
from ugc_bot.infrastructure.db.models import (
    FinancialPolicyVersionModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyFinancialPolicyRepository:
    async def load(
        self, version: str, *, session: object
    ) -> FinancialPolicy | None:
        """Decode the persisted approval; never accept request-supplied rules.

        Like other adapters, the caller owns the session and its commit. A read
        may lazily begin that transaction; no separate connection is acquired.
        """
        if not isinstance(session, AsyncSession):
            raise ValueError("caller_transaction_required")
        model = await session.get(FinancialPolicyVersionModel, version)
        if model is None:
            return None
        return decode_policy_version(model)

    async def lock_active_admin(
        self, actor_id: UUID, *, session: object
    ) -> bool:
        row = (
            await _session(session).execute(
                select(UserModel.admin, UserModel.status)
                .where(UserModel.user_id == actor_id)
                .with_for_update(key_share=True)
            )
        ).one_or_none()
        return bool(row and row.admin and row.status == UserStatus.ACTIVE)

    async def lock_version(self, version: str, *, session: object) -> None:
        await _session(session).execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "financial-policy:" + version},
        )

    async def save_approved(
        self, policy: FinancialPolicy, *, session: object
    ) -> None:
        if policy.refund_rules is None:
            raise ValueError("refund_rules_required")
        await self.add(
            FinancialPolicyVersionModel(
                version=policy.version,
                approved_by=policy.approved_by,
                approved_at=policy.approved_at,
                effective_from=policy.effective_from,
                refund_window_seconds=(
                    policy.refund_rules.selection_refund_window_seconds
                ),
                rules={
                    "allowed_clients": sorted(
                        str(client) for client in policy.allowed_clients
                    ),
                    "terms_reference": policy.terms_reference,
                    "refund_rules": policy.refund_rules.to_document(),
                    "selection_minor": policy.selection_minor,
                    "accompaniment_minor": policy.accompaniment_minor,
                },
            ),
            session=_session(session),
        )

    async def get(
        self, version: str, *, session: AsyncSession
    ) -> FinancialPolicyVersionModel | None:
        return await _session(session).get(FinancialPolicyVersionModel, version)

    async def add(
        self, policy: FinancialPolicyVersionModel, *, session: AsyncSession
    ) -> FinancialPolicyVersionModel:
        db = _session(session)
        db.add(policy)
        await db.flush()
        return policy


def decode_policy_version(
    model: FinancialPolicyVersionModel,
) -> FinancialPolicy:
    """Shared decoder for quote creation and issued/captured invoices."""
    rules = model.rules
    if not isinstance(rules, dict):
        raise ValueError("invalid_policy_document")
    clients = rules.get("allowed_clients")
    terms = rules.get("terms_reference")
    if (
        not isinstance(clients, list)
        or not isinstance(terms, str)
        or not terms.strip()
    ):
        raise ValueError("invalid_policy_document")
    if ("selection_minor" in rules) != ("accompaniment_minor" in rules):
        raise ValueError("invalid_policy_document")
    try:
        if any(not isinstance(client, str) for client in clients):
            raise ValueError("invalid_policy_document")
        allowed = frozenset(UUID(client) for client in clients)
        if any(client.int == 0 for client in allowed):
            raise ValueError("invalid_policy_document")
        return FinancialPolicy(
            selection_minor=rules.get("selection_minor", 50000),
            accompaniment_minor=rules.get("accompaniment_minor", 120000),
            version=model.version,
            approved_by=model.approved_by,
            approved_at=model.approved_at,
            effective_from=model.effective_from,
            selection_refund_window=timedelta(
                seconds=model.refund_window_seconds
            ),
            allowed_clients=allowed,
            terms_reference=terms,
            refund_rules=RefundRules.from_document(rules["refund_rules"])
            if "refund_rules" in rules
            else None,
        )
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("invalid_policy_document") from exc
