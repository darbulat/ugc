"""SQLAlchemy country, language, and bot texts repositories."""

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.ports import (
    BotTextsRepository,
    CountryRepository,
    LanguageRepository,
)
from ugc_bot.domain.entities import Country, Language
from ugc_bot.infrastructure.db.models import (
    BotTextModel,
    CountryModel,
    LanguageModel,
)
from ugc_bot.infrastructure.db.repositories._shared import (
    _get_async_session,
    _resolve_session,
)


@dataclass(slots=True)
class SqlAlchemyCountryRepository(CountryRepository):
    """SQLAlchemy-backed country repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def _execute_in_session(
        self, stmt: Any, session: object | None = None
    ) -> Any:
        """Execute a statement, using the provided session or a new one."""
        if session is not None:
            return await _get_async_session(session).execute(stmt)
        async with self.session_factory() as db_session:
            return await db_session.execute(stmt)

    async def list_enabled(
        self, session: object | None = None
    ) -> list[Country]:
        """List enabled countries."""
        exec_result = await self._execute_in_session(
            select(CountryModel).where(CountryModel.enabled.is_(True)),
            session,
        )
        return [_to_country_entity(row) for row in exec_result.scalars().all()]

    async def get_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[Country]:
        """Fetch country by code."""
        exec_result = await self._execute_in_session(
            select(CountryModel).where(CountryModel.code == code),
            session,
        )
        result = exec_result.scalar_one_or_none()
        return _to_country_entity(result) if result else None

    async def get_by_currency_code(
        self, currency_code: str, session: object | None = None
    ) -> Optional[Country]:
        """Fetch any enabled country with the given currency code."""
        exec_result = await self._execute_in_session(
            select(CountryModel)
            .where(
                CountryModel.currency_code == currency_code,
                CountryModel.enabled.is_(True),
            )
            .limit(1),
            session,
        )
        result = exec_result.scalar_one_or_none()
        return _to_country_entity(result) if result else None


@dataclass(slots=True)
class SqlAlchemyLanguageRepository(LanguageRepository):
    """SQLAlchemy implementation of LanguageRepository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def _execute_in_session(
        self, stmt: Any, session: object | None = None
    ) -> Any:
        """Execute a statement, using the provided session or a new one."""
        if session is not None:
            return await _get_async_session(session).execute(stmt)
        async with self.session_factory() as db_session:
            return await db_session.execute(stmt)

    async def list_enabled(
        self, session: object | None = None
    ) -> list[Language]:
        """List enabled languages."""
        exec_result = await self._execute_in_session(
            select(LanguageModel).where(LanguageModel.enabled.is_(True)),
            session,
        )
        return [_to_language_entity(row) for row in exec_result.scalars().all()]

    async def get_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[Language]:
        """Fetch language by code."""
        exec_result = await self._execute_in_session(
            select(LanguageModel).where(LanguageModel.code == code),
            session,
        )
        result = exec_result.scalar_one_or_none()
        return _to_language_entity(result) if result else None


@dataclass(slots=True)
class SqlAlchemyBotTextsRepository(BotTextsRepository):
    """SQLAlchemy-backed bot texts repository (key, locale -> value)."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get(
        self, key: str, locale: str, session: object | None = None
    ) -> Optional[str]:
        """Fetch text value for key and locale."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(BotTextModel).where(
                    and_(
                        BotTextModel.key == key,
                        BotTextModel.locale == locale,
                    )
                )
            )
            row = exec_result.scalar_one_or_none()
            return row.value if row else None

    async def get_all(
        self, session: object | None = None
    ) -> list[tuple[str, str, str]]:
        """Fetch all bot_texts rows as (key, locale, value)."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(select(BotTextModel))
            rows = exec_result.scalars().all()
            return [(r.key, r.locale, r.value) for r in rows]


def _to_country_entity(model: CountryModel) -> Country:
    """Map country ORM model to domain entity."""
    return Country(
        code=model.code,
        name_native=model.name_native,
        currency_code=model.currency_code,
        currency_symbol=model.currency_symbol,
        tax_rate=model.tax_rate,
        enabled=model.enabled,
    )


def _to_language_entity(model: LanguageModel) -> Language:
    """Map language ORM model to domain entity."""
    return Language(
        code=model.code,
        name_native=model.name_native,
        enabled=model.enabled,
    )
