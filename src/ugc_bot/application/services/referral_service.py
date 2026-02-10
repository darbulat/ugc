"""Service for referral link handling and pending bindings."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from ugc_bot.application.ports import (
    CreatorManagerBindingRepository,
    ManagerRepository,
    TransactionManager,
    UserReferralPendingRepository,
)
from ugc_bot.domain.entities import CreatorManagerBinding, UserReferralPending
from ugc_bot.infrastructure.db.session import with_optional_tx

REFERRAL_PREFIX = "ref_"


@dataclass(slots=True)
class ReferralService:
    """Handle referral links and creator-manager bindings."""

    manager_repo: ManagerRepository
    user_referral_pending_repo: UserReferralPendingRepository
    creator_manager_binding_repo: CreatorManagerBindingRepository
    transaction_manager: TransactionManager | None = None

    def parse_referral_code(self, text: str | None) -> str | None:
        """Extract referral code from /start ref_XXX payload.

        Returns referral code (without ref_ prefix) or None.
        """
        if not text or not text.strip():
            return None
        parts = text.strip().split(maxsplit=1)
        if len(parts) < 2:
            return None
        payload = parts[1].strip()
        if payload.startswith(REFERRAL_PREFIX):
            return payload[len(REFERRAL_PREFIX) :].strip()
        return None

    async def save_pending_referral(
        self, user_id: UUID, referral_code: str
    ) -> bool:
        """Save pending referral if manager exists. Returns True if saved."""

        async def _run(session: object | None) -> bool:
            manager = await self.manager_repo.get_by_referral_code(
                referral_code, session=session
            )
            if manager is None:
                return False

            existing = await self.user_referral_pending_repo.get_by_user(
                user_id, session=session
            )
            if existing is not None:
                return True

            pending = UserReferralPending(
                user_id=user_id,
                manager_id=manager.manager_id,
                created_at=datetime.now(timezone.utc),
            )
            await self.user_referral_pending_repo.save(pending, session=session)
            return True

        return await with_optional_tx(self.transaction_manager, _run)

    async def create_binding_from_pending(
        self,
        creator_user_id: UUID,
        session: object | None = None,
    ) -> Optional[CreatorManagerBinding]:
        """Create creator-manager binding from pending referral if exists.

        Deletes pending after binding. Returns binding or None.
        When session is provided, uses it; otherwise opens own transaction.
        """

        async def _run(sess: object | None) -> Optional[CreatorManagerBinding]:
            pending = await self.user_referral_pending_repo.get_by_user(
                creator_user_id, session=sess
            )
            if pending is None:
                return None

            existing = await self.creator_manager_binding_repo.get_by_creator(
                creator_user_id, session=sess
            )
            if existing is not None:
                await self.user_referral_pending_repo.delete_by_user(
                    creator_user_id, session=sess
                )
                return existing

            binding = CreatorManagerBinding(
                creator_user_id=creator_user_id,
                manager_id=pending.manager_id,
                created_at=datetime.now(timezone.utc),
            )
            await self.creator_manager_binding_repo.save(binding, session=sess)
            await self.user_referral_pending_repo.delete_by_user(
                creator_user_id, session=sess
            )
            return binding

        if session is not None:
            return await _run(session)
        return await with_optional_tx(self.transaction_manager, _run)
