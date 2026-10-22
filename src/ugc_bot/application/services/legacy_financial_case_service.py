"""Operational review of legacy safety cases; not a financial ledger."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


class LegacyFinancialCaseRepository(Protocol):
    async def review(
        self,
        interaction_id: UUID,
        *,
        actor_id: UUID,
        expected_version: int,
        command_id: UUID,
        decision: str,
        reason: str,
        confirmed_result: bool,
    ) -> dict[str, Any]: ...

    async def list_cases(
        self,
        actor_id: UUID,
        interaction_id: UUID | None = None,
        *,
        after: UUID | None = None,
        limit: int = 200,
        released: bool | None = None,
    ) -> list[dict[str, Any]]: ...


@dataclass
class LegacyFinancialCaseService:
    repository: LegacyFinancialCaseRepository

    async def review(
        self,
        interaction_id: UUID,
        *,
        actor_id: UUID,
        expected_version: int,
        command_id: UUID,
        decision: str,
        reason: str,
        confirmed_result: bool = False,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("Financial review reason is required")
        if decision not in {"release_no_adjustment", "keep_blocked"}:
            raise ValueError("Unsupported financial decision")
        if decision == "release_no_adjustment" and not confirmed_result:
            raise ValueError("Explicit confirmed legacy result is required")
        return await self.repository.review(
            interaction_id,
            actor_id=actor_id,
            expected_version=expected_version,
            command_id=command_id,
            decision=decision,
            reason=reason.strip(),
            confirmed_result=confirmed_result,
        )

    async def list_cases(
        self,
        actor_id: UUID,
        interaction_id: UUID | None = None,
        *,
        after: UUID | None = None,
        limit: int = 200,
        released: bool | None = None,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200:
            raise ValueError("Case page limit must be between 1 and 200")
        return await self.repository.list_cases(
            actor_id,
            interaction_id,
            after=after,
            limit=limit,
            released=released,
        )
