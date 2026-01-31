"""Service for saving and restoring FSM drafts when user clicks Support."""

from typing import Any, AsyncContextManager, Protocol
from uuid import UUID

from ugc_bot.application.ports import FsmDraftRepository
from ugc_bot.domain.entities import FsmDraft
from ugc_bot.infrastructure.db.session import with_optional_tx


class TransactionManager(Protocol):
    """Protocol for database transaction handling."""

    def transaction(self) -> AsyncContextManager[Any]:
        """Return a context manager for a transaction."""


class FsmDraftService:
    """Save and restore FSM drafts (partial form data) on Support button."""

    def __init__(
        self,
        draft_repo: FsmDraftRepository,
        transaction_manager: TransactionManager | None = None,
    ) -> None:
        """Initialize with draft repository and optional transaction manager."""
        self._draft_repo = draft_repo
        self._transaction_manager = transaction_manager

    async def save_draft(
        self,
        user_id: UUID,
        flow_type: str,
        state_key: str,
        data: dict,
    ) -> None:
        """Save or overwrite draft for user and flow type."""

        async def _run(session: object | None) -> None:
            await self._draft_repo.save(
                user_id=user_id,
                flow_type=flow_type,
                state_key=state_key,
                data=data,
                session=session,
            )

        await with_optional_tx(self._transaction_manager, _run)

    async def get_draft(
        self,
        user_id: UUID,
        flow_type: str,
    ) -> FsmDraft | None:
        """Get draft for user and flow type, or None."""

        async def _run(session: object | None) -> FsmDraft | None:
            return await self._draft_repo.get(
                user_id=user_id,
                flow_type=flow_type,
                session=session,
            )

        return await with_optional_tx(self._transaction_manager, _run)

    async def delete_draft(
        self,
        user_id: UUID,
        flow_type: str,
    ) -> None:
        """Delete draft for user and flow type."""

        async def _run(session: object | None) -> None:
            await self._draft_repo.delete(
                user_id=user_id,
                flow_type=flow_type,
                session=session,
            )

        await with_optional_tx(self._transaction_manager, _run)
