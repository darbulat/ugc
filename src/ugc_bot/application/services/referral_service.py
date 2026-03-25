"""Service for referral link handling and pending bindings."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from ugc_bot.application.ports import (
    TransactionManager,
    UserReferralBindingRepository,
    UserReferralPendingRepository,
    UserRepository,
)
from ugc_bot.domain.entities import (
    UserReferralBinding,
    UserReferralPending,
)
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)

REFERRAL_PREFIX = "ref_"
_REFERRAL_CODE_RE = re.compile(r"^[a-z0-9]{4,20}$")


@dataclass(slots=True)
class ReferralService:
    """Handle referral links and user referral bindings."""

    user_repo: UserRepository
    user_referral_pending_repo: UserReferralPendingRepository
    user_referral_binding_repo: UserReferralBindingRepository
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
            code = payload[len(REFERRAL_PREFIX) :].strip().lower()
            if code and _REFERRAL_CODE_RE.match(code):
                return code
        return None

    async def save_pending_referral(
        self, user_id: UUID, referral_code: str
    ) -> bool:
        """Save pending referral if referrer exists.

        Returns True if saved, user already had a pending referral,
        or user already has a binding (no pending needed).
        Does not create pending when user is already referred (has binding).
        """

        async def _run(session: object | None) -> bool:
            referrer = await self.user_repo.get_by_referral_code(
                referral_code, session=session
            )
            if referrer is None:
                return False
            if referrer.user_id == user_id:
                return False

            existing = await self.user_referral_pending_repo.get_by_user(
                user_id, session=session
            )
            if existing is not None:
                return True

            existing_binding = (
                await self.user_referral_binding_repo.get_by_referred_user(
                    user_id, session=session
                )
            )
            if existing_binding is not None:
                return True

            pending = UserReferralPending(
                user_id=user_id,
                referrer_user_id=referrer.user_id,
                created_at=datetime.now(timezone.utc),
            )
            await self.user_referral_pending_repo.save(pending, session=session)
            return True

        return await with_optional_tx(self.transaction_manager, _run)

    async def create_binding_from_pending(
        self,
        creator_user_id: UUID,
        session: object | None = None,
    ) -> Optional[UserReferralBinding]:
        """Create user referral binding from pending if exists.

        Deletes pending after binding. Returns binding or None.
        When session is provided, uses it; otherwise opens own transaction.
        """

        async def _run(sess: object | None) -> Optional[UserReferralBinding]:
            pending = await self.user_referral_pending_repo.get_by_user(
                creator_user_id, session=sess
            )
            if pending is None:
                return None

            existing = (
                await self.user_referral_binding_repo.get_by_referred_user(
                    creator_user_id, session=sess
                )
            )
            if existing is not None:
                await self.user_referral_pending_repo.delete_by_user(
                    creator_user_id, session=sess
                )
                return existing

            binding = UserReferralBinding(
                referrer_user_id=pending.referrer_user_id,
                referred_user_id=creator_user_id,
                created_at=datetime.now(timezone.utc),
            )
            (
                result,
                created,
            ) = await self.user_referral_binding_repo.save_or_get_existing(
                binding, session=sess
            )
            if not created:
                logger.warning(
                    "Concurrent referral binding creation for user %s",
                    creator_user_id,
                )
            await self.user_referral_pending_repo.delete_by_user(
                creator_user_id, session=sess
            )
            return result

        if session is not None:
            return await _run(session)
        return await with_optional_tx(self.transaction_manager, _run)
