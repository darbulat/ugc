"""Tests for BotTextsService."""

import pytest

from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS


class FakeBotTextsRepo:
    """Fake repo: get_all() returns preconfigured rows; get() for single key."""

    def __init__(
        self,
        get_all_rows: list[tuple[str, str, str]] | None = None,
        get_value: str | None = None,
    ):
        self.get_all_rows = get_all_rows or []
        self.get_value = get_value
        self.get_all_calls = 0
        self.get_calls: list[tuple[str, str]] = []

    async def get(
        self, key: str, locale: str, session: object | None = None
    ) -> str | None:
        self.get_calls.append((key, locale))
        return self.get_value

    async def get_all(
        self, session: object | None = None
    ) -> list[tuple[str, str, str]]:
        self.get_all_calls += 1
        return self.get_all_rows


@pytest.mark.asyncio
async def test_get_returns_from_preloaded_cache_after_load_from_db() -> None:
    """After load_from_db(), get() returns value from DB, no per-get DB call."""
    repo = FakeBotTextsRepo(get_all_rows=[("start_message", "ru", "From DB")])
    svc = BotTextsService(bot_texts_repo=repo, default_locale="ru")
    await svc.load_from_db()
    result = await svc.get("start_message", "ru")
    assert result == "From DB"
    assert repo.get_all_calls == 1
    assert repo.get_calls == []


@pytest.mark.asyncio
async def test_get_fallback_to_defaults_when_not_loaded() -> None:
    """When load_from_db() not called, get() falls back to DEFAULT_TEXTS."""
    repo = FakeBotTextsRepo(get_all_rows=[])
    svc = BotTextsService(bot_texts_repo=repo, default_locale="ru")
    result = await svc.get("start_message", "ru")
    assert result == DEFAULT_TEXTS["ru"]["start_message"]


@pytest.mark.asyncio
async def test_get_when_not_loaded_and_key_missing_returns_empty() -> None:
    """Not loaded and key not in DEFAULT_TEXTS -> get() returns empty string."""
    repo = FakeBotTextsRepo(get_all_rows=[])
    svc = BotTextsService(bot_texts_repo=repo, default_locale="ru")
    result = await svc.get("nonexistent_key_xyz", "ru")
    assert result == ""


@pytest.mark.asyncio
async def test_get_fallback_to_defaults_after_load_empty_db() -> None:
    """load_from_db() empty: defaults merged, get() returns them."""
    repo = FakeBotTextsRepo(get_all_rows=[])
    svc = BotTextsService(bot_texts_repo=repo, default_locale="ru")
    await svc.load_from_db()
    result = await svc.get("start_message", "ru")
    assert result == DEFAULT_TEXTS["ru"]["start_message"]


@pytest.mark.asyncio
async def test_get_uses_default_locale_when_none_passed() -> None:
    """When locale is None, default_locale is used."""
    repo = FakeBotTextsRepo(get_all_rows=[])
    svc = BotTextsService(bot_texts_repo=repo, default_locale="en")
    await svc.load_from_db()
    result = await svc.get("support_response", None)
    assert result == DEFAULT_TEXTS["en"]["support_response"]


@pytest.mark.asyncio
async def test_get_returns_empty_when_no_default() -> None:
    """Key not in store and not in defaults -> returns empty string."""
    repo = FakeBotTextsRepo(get_all_rows=[])
    svc = BotTextsService(bot_texts_repo=repo, default_locale="ru")
    await svc.load_from_db()
    result = await svc.get("unknown_key_xyz", "ru")
    assert result == ""


@pytest.mark.asyncio
async def test_get_reads_from_memory_after_load_no_extra_db_calls() -> None:
    """After load_from_db(), multiple get() calls do not call repo again."""
    repo = FakeBotTextsRepo(get_all_rows=[("start_message", "ru", "Cached")])
    svc = BotTextsService(bot_texts_repo=repo, default_locale="ru")
    await svc.load_from_db()
    r1 = await svc.get("start_message", "ru")
    r2 = await svc.get("start_message", "ru")
    assert r1 == r2 == "Cached"
    assert repo.get_all_calls == 1
    assert repo.get_calls == []


@pytest.mark.asyncio
async def test_invalidate_cache_clears_store_next_get_uses_defaults() -> None:
    """invalidate_cache() clears store; next get() uses DEFAULT_TEXTS."""
    repo = FakeBotTextsRepo(get_all_rows=[("start_message", "ru", "V1")])
    svc = BotTextsService(bot_texts_repo=repo, default_locale="ru")
    await svc.load_from_db()
    await svc.get("start_message", "ru")
    svc.invalidate_cache()
    result = await svc.get("start_message", "ru")
    assert result == DEFAULT_TEXTS["ru"]["start_message"]


@pytest.mark.asyncio
async def test_load_from_db_on_repo_error_uses_defaults_only() -> None:
    """If load_from_db() fails, service falls back to DEFAULT_TEXTS only."""

    class FailingRepo(FakeBotTextsRepo):
        async def get_all(
            self, session: object | None = None
        ) -> list[tuple[str, str, str]]:
            raise RuntimeError("DB unavailable")

    repo = FailingRepo(get_all_rows=[])
    svc = BotTextsService(bot_texts_repo=repo, default_locale="ru")
    await svc.load_from_db()
    result = await svc.get("start_message", "ru")
    assert result == DEFAULT_TEXTS["ru"]["start_message"]


@pytest.mark.asyncio
async def test_get_many_returns_dict() -> None:
    """get_many returns key -> text for each key, using get() fallback."""
    repo = FakeBotTextsRepo(get_all_rows=[])
    svc = BotTextsService(bot_texts_repo=repo, default_locale="ru")
    await svc.load_from_db()
    result = await svc.get_many(["start_message", "support_response"], "ru")
    assert result["start_message"] == DEFAULT_TEXTS["ru"]["start_message"]
    assert result["support_response"] == DEFAULT_TEXTS["ru"]["support_response"]


@pytest.mark.asyncio
async def test_get_loaded_but_key_missing_in_cache_uses_defaults() -> None:
    """When loaded from DB but key not in cache, fall back to DEFAULT_TEXTS."""
    repo = FakeBotTextsRepo(
        get_all_rows=[("other_key", "ru", "Other")]  # not start_message
    )
    svc = BotTextsService(bot_texts_repo=repo, default_locale="ru")
    await svc.load_from_db()
    result = await svc.get("start_message", "ru")
    assert result == DEFAULT_TEXTS["ru"]["start_message"]
