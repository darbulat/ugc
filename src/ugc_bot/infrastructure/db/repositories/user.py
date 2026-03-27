"""SQLAlchemy user repository."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.ports import UserRepository
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session


@dataclass(slots=True)
class SqlAlchemyUserRepository(UserRepository):
    """SQLAlchemy-backed user repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by ID."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(UserModel).where(UserModel.user_id == user_id)
            )
            result = exec_result.scalar_one_or_none()
            return _to_user_entity(result) if result else None

    async def get_by_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, User]:
        """Fetch users by IDs in one query."""
        if not user_ids:
            return {}
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(UserModel).where(UserModel.user_id.in_(user_ids))
            )
            rows = exec_result.scalars().all()
            return {row.user_id: _to_user_entity(row) for row in rows}

    async def get_by_external(
        self,
        external_id: str,
        messenger_type: MessengerType,
        session: object | None = None,
    ) -> Optional[User]:
        """Fetch a user by external messenger id."""
        if messenger_type == MessengerType.TELEGRAM:
            col = UserModel.telegram_id
        elif messenger_type == MessengerType.MAX:
            col = UserModel.max_id
        else:
            return None
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(UserModel).where(col == external_id)
            )
            result = exec_result.scalar_one_or_none()
            return _to_user_entity(result) if result else None

    async def get_by_referral_code(
        self, referral_code: str, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by referral code."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(UserModel).where(
                    UserModel.referral_code == referral_code,
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_user_entity(result) if result else None

    async def get_by_telegram(
        self, telegram: str, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by Telegram username (case-insensitive, @ stripped)."""
        normalized = (telegram or "").strip().lstrip("@").lower()
        if not normalized:
            return None
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(UserModel).where(
                    func.lower(UserModel.telegram) == normalized,
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_user_entity(result) if result else None

    async def save(self, user: User, session: object | None = None) -> None:
        """Persist a user."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = _to_user_model(user)
            await db_session.merge(model)

    async def list_pending_role_reminders(
        self, reminder_cutoff: datetime, session: object | None = None
    ) -> Iterable[User]:
        """List users who have not chosen a role and are due for a reminder."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(UserModel).where(
                    UserModel.role_chosen_at.is_(None),
                    (UserModel.last_role_reminder_at.is_(None))
                    | (UserModel.last_role_reminder_at < reminder_cutoff),
                )
            )
            results = exec_result.scalars().all()
            return [_to_user_entity(row) for row in results]

    async def list_admins(
        self,
        messenger_type: MessengerType | None = None,
        session: object | None = None,
    ) -> Iterable[User]:
        """List users with admin=True. Optionally filter by messenger_type."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            query = select(UserModel).where(UserModel.admin.is_(True))
            if messenger_type == MessengerType.TELEGRAM:
                query = query.where(UserModel.telegram_id.isnot(None))
            elif messenger_type == MessengerType.MAX:
                query = query.where(UserModel.max_id.isnot(None))
            exec_result = await db_session.execute(query)
            results = exec_result.scalars().all()
            return [_to_user_entity(row) for row in results]


def _to_user_entity(model: UserModel) -> User:
    """Map user ORM model to domain entity."""
    return User(
        user_id=model.user_id,
        messenger_type=model.messenger_type,
        username=model.username,
        status=model.status,
        issue_count=model.issue_count,
        created_at=model.created_at,
        telegram_id=model.telegram_id,
        max_id=model.max_id,
        max_chat_id=model.max_chat_id,
        role_chosen_at=model.role_chosen_at,
        last_role_reminder_at=model.last_role_reminder_at,
        telegram=model.telegram,
        admin=model.admin,
        referral_code=model.referral_code,
        referral_payout_rate=model.referral_payout_rate,
        updated_at=model.updated_at,
        country=model.country,
        language=model.language,
    )


def _to_user_model(user: User) -> UserModel:
    """Map domain user entity to ORM model."""
    from datetime import timezone

    return UserModel(
        user_id=user.user_id,
        telegram_id=user.telegram_id,
        max_id=user.max_id,
        max_chat_id=user.max_chat_id,
        messenger_type=user.messenger_type,
        username=user.username,
        status=user.status,
        issue_count=user.issue_count,
        created_at=user.created_at,
        role_chosen_at=user.role_chosen_at,
        last_role_reminder_at=user.last_role_reminder_at,
        telegram=user.telegram,
        admin=user.admin,
        referral_code=user.referral_code,
        referral_payout_rate=user.referral_payout_rate,
        updated_at=user.updated_at or datetime.now(timezone.utc),
        country=user.country,
        language=user.language,
    )
