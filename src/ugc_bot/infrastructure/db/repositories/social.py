"""Atomic, canonical-owner social account upserts."""

from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ugc_bot.application.legacy_link_ports import LegacySqlParticipant
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.application.social_ports import (
    SocialAccountRepository,
    SocialEditorFacts,
)
from ugc_bot.domain.enums import WorkFormat
from ugc_bot.domain.social import SocialAccount, SocialPlatform
from ugc_bot.infrastructure.db.models import BloggerProfileModel, UserModel
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session
from ugc_bot.infrastructure.db.repositories.profiles import (
    _to_blogger_profile_entity,
)
from ugc_bot.infrastructure.db.social_models import SocialAccountModel


def _entity(model: SocialAccountModel) -> SocialAccount:
    return SocialAccount(
        account_id=model.account_id,
        user_id=model.user_id,
        platform=SocialPlatform(model.platform),
        url=model.url,
        handle=model.handle,
        verified=model.verified,
        external_id=model.external_id,
        work_format=WorkFormat(model.work_format),
        followers_count=model.followers_count,
        metrics_source=model.metrics_source,
        metrics_fetched_at=model.metrics_fetched_at,
        verified_at=model.verified_at,
        verification_observed_at=model.verification_observed_at,
        verification_source=model.verification_source,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@dataclass(slots=True)
class SqlAlchemySocialAccountRepository(
    SocialAccountRepository, LegacySqlParticipant
):
    session_factory: async_sessionmaker[AsyncSession]

    def _editor_session(self, session: object) -> AsyncSession:
        if not isinstance(session, AsyncSession):
            raise ValueError("social_unavailable")
        transaction = session.sync_session.get_transaction()
        configured = self.session_factory.kw.get("bind")
        if (
            transaction is None
            or not transaction.is_active
            or session.in_nested_transaction()
            or session.new
            or session.dirty
            or session.deleted
            or not isinstance(configured, AsyncEngine)
        ):
            raise ValueError("social_unavailable")
        for mapper in (UserModel, BloggerProfileModel, SocialAccountModel):
            actual = session.get_bind(mapper=mapper)
            engine = actual.engine if isinstance(actual, Connection) else actual
            if engine is not configured.sync_engine:
                raise ValueError("social_unavailable")
        return session

    @staticmethod
    async def _editor_actor(
        db: AsyncSession,
        user_id: UUID,
        principal: AuthenticatedMessengerPrincipal,
        *,
        lock: bool,
    ) -> None:
        if (
            not isinstance(principal, AuthenticatedMessengerPrincipal)
            or principal.user_id != user_id
        ):
            raise ValueError("financial_principal_changed")
        statement = (
            select(
                UserModel.user_id,
                UserModel.status,
                UserModel.telegram_id,
                UserModel.max_id,
            )
            .where(UserModel.user_id == user_id)
            .execution_options(autoflush=False)
        )
        if lock:
            statement = statement.with_for_update(key_share=True)
        row = (await db.execute(statement)).one_or_none()
        require_current_principal(
            principal,
            user_id,
            row.user_id if row else None,
            row.telegram_id if row else None,
            row.max_id if row else None,
        )
        if row is None or row.status in {"blocked", "bot_blocked", "deleted"}:
            raise ValueError("social_account_unavailable")

    @staticmethod
    async def _editor_facts(
        db: AsyncSession,
        user_id: UUID,
        *,
        lock: bool,
    ) -> SocialEditorFacts:
        profile_query = (
            select(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == user_id)
            .execution_options(autoflush=False, populate_existing=True)
        )
        account_query = (
            select(SocialAccountModel)
            .where(SocialAccountModel.user_id == user_id)
            .order_by(SocialAccountModel.account_id)
            .execution_options(autoflush=False, populate_existing=True)
        )
        if lock:
            profile_query = profile_query.with_for_update(read=True)
            account_query = account_query.with_for_update()
        profile = await db.scalar(profile_query)
        accounts = tuple(
            _entity(row) for row in (await db.scalars(account_query))
        )
        return SocialEditorFacts(
            user_id,
            _to_blogger_profile_entity(profile) if profile else None,
            accounts,
        )

    async def read_editor(
        self,
        user_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal,
        session: object,
    ) -> SocialEditorFacts:
        db = self._editor_session(session)
        await db.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )
        await self._editor_actor(db, user_id, principal, lock=False)
        return await self._editor_facts(db, user_id, lock=False)

    async def prepare_editor_write(
        self,
        user_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal,
        session: object,
    ) -> SocialEditorFacts:
        db = self._editor_session(session)
        await self._editor_actor(db, user_id, principal, lock=True)
        return await self._editor_facts(db, user_id, lock=True)

    async def list_accounts(
        self,
        user_id: UUID,
        session: object | None = None,
    ) -> list[SocialAccount]:
        async with _resolve_session(self.session_factory, session) as db:
            result = await db.scalars(
                select(SocialAccountModel)
                .where(
                    SocialAccountModel.user_id == user_id,
                )
                .order_by(SocialAccountModel.platform)
                .execution_options(autoflush=False, populate_existing=True)
            )
            return [_entity(row) for row in result]

    async def get_by_id(
        self,
        account_id: UUID,
        session: object | None = None,
    ) -> SocialAccount | None:
        async with _resolve_session(self.session_factory, session) as db:
            row = await db.scalar(
                select(SocialAccountModel)
                .where(SocialAccountModel.account_id == account_id)
                .execution_options(autoflush=False, populate_existing=True)
            )
            return _entity(row) if row is not None else None

    async def save(
        self,
        account: SocialAccount,
        session: object | None = None,
    ) -> SocialAccount:
        async with _resolve_session(self.session_factory, session) as db:
            values = asdict(account)
            insert = (
                sqlite_insert
                if db.get_bind().dialect.name == "sqlite"
                else pg_insert
            )
            statement = insert(SocialAccountModel).values(**values)
            updates = {
                key: value
                for key, value in values.items()
                if key
                not in {"account_id", "user_id", "platform", "created_at"}
            }
            result_statement = statement.on_conflict_do_update(
                index_elements=["user_id", "platform"],
                set_=updates,
            ).returning(SocialAccountModel)
            result = await db.execute(
                result_statement.execution_options(populate_existing=True)
            )
            return _entity(result.scalar_one())

    async def remove(
        self,
        user_id: UUID,
        account_id: UUID,
        session: object | None = None,
    ) -> bool:
        async with _resolve_session(self.session_factory, session) as db:
            result = await db.execute(
                delete(SocialAccountModel)
                .where(
                    SocialAccountModel.user_id == user_id,
                    SocialAccountModel.account_id == account_id,
                )
                .returning(SocialAccountModel.account_id)
            )
            return result.scalar_one_or_none() is not None
