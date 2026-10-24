"""SQLAlchemy user repository."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, SessionTransaction

from ugc_bot.application.legacy_link_ports import (
    LegacyMaxAttachment,
    LegacyMaxPreparation,
    LegacySqlParticipant,
    attachment_state,
    validated_max_chat_id,
)
from ugc_bot.application.ports import UserRepository
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.repositories import messenger_linking
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session

_LEGACY_MAX_PREPARATIONS = "legacy_max_preparations"


@dataclass(slots=True)
class _LegacyMaxCapabilities:
    transaction: SessionTransaction
    preparations: list[LegacyMaxPreparation]


def _expire_legacy_max_capabilities(
    session: Session, transaction: SessionTransaction
) -> None:
    registered = session.info.get(_LEGACY_MAX_PREPARATIONS)
    if (
        isinstance(registered, _LegacyMaxCapabilities)
        and registered.transaction is transaction
    ):
        session.info.pop(_LEGACY_MAX_PREPARATIONS)


def _register_legacy_max_preparation(
    session: AsyncSession,
    transaction: SessionTransaction,
    preparation: LegacyMaxPreparation,
) -> None:
    # One stable session handler, independent of preparation/root count.
    if not event.contains(
        session.sync_session,
        "after_transaction_end",
        _expire_legacy_max_capabilities,
    ):
        event.listen(
            session.sync_session,
            "after_transaction_end",
            _expire_legacy_max_capabilities,
        )
    registered = session.info.get(_LEGACY_MAX_PREPARATIONS)
    if (
        not isinstance(registered, _LegacyMaxCapabilities)
        or registered.transaction is not transaction
    ):
        registered = _LegacyMaxCapabilities(transaction, [])
        session.info[_LEGACY_MAX_PREPARATIONS] = registered
    registered.preparations.append(preparation)


def _current_legacy_max_preparation(
    session: AsyncSession, preparation: LegacyMaxPreparation
) -> bool:
    registered = session.info.get(_LEGACY_MAX_PREPARATIONS)
    transaction = session.sync_session.get_transaction()
    return (
        isinstance(registered, _LegacyMaxCapabilities)
        and transaction is registered.transaction
        and transaction.is_active
        and any(item is preparation for item in registered.preparations)
    )


@dataclass(slots=True)
class SqlAlchemyUserRepository(UserRepository, LegacySqlParticipant):
    """SQLAlchemy-backed user repository."""

    session_factory: async_sessionmaker[AsyncSession]

    def legacy_confirmation_supported(self, session, participants):
        return (
            isinstance(session, AsyncSession)
            and session.in_transaction()
            and all(
                isinstance(repo, LegacySqlParticipant) for repo in participants
            )
        )

    async def _legacy_user(self, db, condition, *, lock=False):
        query = (
            select(UserModel)
            .where(condition)
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update(key_share=True)
        model = await db.scalar(query)
        return _to_user_entity(model) if model is not None else None

    async def prepare_legacy_max_attachment(
        self,
        target_id,
        *,
        code_id=None,
        max_id=None,
        max_chat_id=None,
        session=None,
    ):
        if not self.legacy_confirmation_supported(session, (self,)):
            return LegacyMaxPreparation(target_id, code_id, max_id, max_chat_id)
        db = session
        # Barriers acquired inside a savepoint may disappear on its rollback.
        if db.in_nested_transaction():
            return LegacyMaxPreparation(
                target_id,
                code_id,
                max_id,
                max_chat_id,
                reason="nested_transaction_unavailable",
            )
        transaction = db.sync_session.get_transaction()
        if transaction is None or not transaction.is_active:
            return LegacyMaxPreparation(target_id, code_id, max_id, max_chat_id)
        owner = (
            await self._legacy_user(db, UserModel.max_id == max_id)
            if max_id is not None
            else None
        )
        scope = tuple(
            sorted({target_id} | ({owner.user_id} if owner else set()), key=str)
        )
        for uid in scope:
            await self._legacy_user(db, UserModel.user_id == uid, lock=True)
        if max_id is not None:
            await messenger_linking.acquire_link_identity_barrier(db)
        current_owner = (
            await self._legacy_user(db, UserModel.max_id == max_id)
            if max_id is not None
            else None
        )
        if (current_owner.user_id if current_owner else None) != (
            owner.user_id if owner else None
        ):
            return LegacyMaxPreparation(
                target_id,
                code_id,
                max_id,
                max_chat_id,
                reason="native_scope_changed",
            )
        target = await self._legacy_user(db, UserModel.user_id == target_id)
        state, reason = attachment_state(target, current_owner, max_id)
        chat = validated_max_chat_id(max_chat_id)
        if max_chat_id is not None and chat is None:
            state, reason = "unavailable", "recorded_chat_invalid"
        preparation = LegacyMaxPreparation(
            target_id,
            code_id,
            max_id,
            chat,
            scope if target is not None else (),
            state,
            reason,
            current_owner.language or "ru" if current_owner else "ru",
            db,
        )
        if preparation.protected:
            if (
                db.sync_session.get_transaction() is not transaction
                or not transaction.is_active
            ):
                return LegacyMaxPreparation(
                    target_id,
                    code_id,
                    max_id,
                    max_chat_id,
                    reason="transaction_changed",
                )
            _register_legacy_max_preparation(db, transaction, preparation)
        return preparation

    async def attach_prepared_max(self, preparation, *, session):
        if (
            not self.legacy_confirmation_supported(session, (self,))
            or preparation.session is not session
            or not preparation.protected
            or not _current_legacy_max_preparation(session, preparation)
        ):
            return LegacyMaxAttachment("unavailable", "preparation_unavailable")
        if preparation.state not in ("ready", "same_account"):
            return LegacyMaxAttachment(preparation.state, preparation.reason)
        target = await self._legacy_user(
            session, UserModel.user_id == preparation.target_id
        )
        owner = (
            await self._legacy_user(
                session, UserModel.max_id == preparation.max_id
            )
            if preparation.max_id is not None
            else None
        )
        state, reason = attachment_state(target, owner, preparation.max_id)
        if state != "ready" or preparation.max_id is None:
            return LegacyMaxAttachment(state, reason, target)
        try:
            async with session.begin_nested():
                updated = await session.scalar(
                    update(UserModel)
                    .where(
                        UserModel.user_id == preparation.target_id,
                        UserModel.max_id.is_(None),
                    )
                    .values(
                        max_id=preparation.max_id,
                        max_chat_id=preparation.max_chat_id,
                    )
                    .returning(UserModel)
                    .execution_options(populate_existing=True)
                )
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) != "23505":
                raise
            return LegacyMaxAttachment("conflict", "native_identity_taken")
        if updated is None:
            return LegacyMaxAttachment("conflict", "target_changed")
        return LegacyMaxAttachment(
            "ready", "attached", _to_user_entity(updated)
        )

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
