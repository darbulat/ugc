"""Localized bot texts: preloaded from DB at startup with code defaults."""

import logging
from dataclasses import dataclass, field
from typing import Any

from ugc_bot.application.ports import BotTextsRepository
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BotTextsService:
    """Resolve bot text by key and locale.

    All messages are loaded from DB into memory at startup via load_from_db().
    get() uses in-memory store and DEFAULT_TEXTS fallback for missing keys.
    """

    bot_texts_repo: BotTextsRepository
    default_locale: str = "ru"
    transaction_manager: Any = None
    _cache: dict[tuple[str, str], str] = field(default_factory=dict, init=False)
    _loaded: bool = field(default=False, init=False)

    async def load_from_db(self) -> None:
        """Load all texts from DB at startup and merge with DEFAULT_TEXTS.

        Call once after application start. Subsequent get() use only memory.
        Uses transaction_manager when set to provide a DB session to the repo.
        """

        async def _load(session: object | None) -> list[tuple[str, str, str]]:
            return await self.bot_texts_repo.get_all(session=session)

        try:
            rows = await with_optional_tx(self.transaction_manager, _load)
            for key, locale, value in rows:
                self._cache[(key, locale)] = value
            count = len(rows)

            for loc, defaults in DEFAULT_TEXTS.items():
                for key, text in defaults.items():
                    if (key, loc) not in self._cache:
                        self._cache[(key, loc)] = text

            self._loaded = True
            logger.info(
                "Bot texts loaded from DB",
                extra={"db_rows": count, "total_keys": len(self._cache)},
            )
        except Exception:
            logger.warning(
                "Could not load bot_texts from DB, using defaults only",
                exc_info=True,
            )
            for loc, defaults in DEFAULT_TEXTS.items():
                for key, text in defaults.items():
                    self._cache[(key, loc)] = text
            self._loaded = True

    async def get(self, key: str, locale: str | None = None) -> str:
        """Return text for key and locale from in-memory store.

        Uses data loaded at startup (load_from_db). If not loaded yet or key
        missing, falls back to DEFAULT_TEXTS. Returns empty string if not found.
        """
        loc = locale or self.default_locale
        cache_key = (key, loc)
        if cache_key in self._cache:
            return self._cache[cache_key]

        if not self._loaded:
            for try_loc in (loc, self.default_locale):
                defaults = DEFAULT_TEXTS.get(try_loc, {})
                if key in defaults:
                    return defaults[key]
            return ""

        for try_loc in (loc, self.default_locale):
            defaults = DEFAULT_TEXTS.get(try_loc, {})
            if key in defaults:
                return defaults[key]
        return ""

    async def get_many(
        self, keys: list[str], locale: str | None = None
    ) -> dict[str, str]:
        """Return dict key -> text for many keys. Same fallback as get()."""
        loc = locale or self.default_locale
        return {k: await self.get(k, loc) for k in keys}

    def invalidate_cache(self) -> None:
        """Clear in-memory store. Call load_from_db() again to reload."""
        self._cache.clear()
        self._loaded = False
