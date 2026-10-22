"""Immutable approved policy persistence in the caller's transaction."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
)
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel
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
        try:
            if any(not isinstance(client, str) for client in clients):
                raise ValueError("invalid_policy_document")
            allowed = frozenset(UUID(client) for client in clients)
            if any(client.int == 0 for client in allowed):
                raise ValueError("invalid_policy_document")
            window = timedelta(seconds=model.refund_window_seconds)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("invalid_policy_document") from exc
        return FinancialPolicy(
            version=model.version,
            approved_by=model.approved_by,
            approved_at=model.approved_at,
            effective_from=model.effective_from,
            selection_refund_window=window,
            allowed_clients=allowed,
            terms_reference=terms,
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
