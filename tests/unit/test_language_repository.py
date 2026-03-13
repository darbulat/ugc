"""Tests for LanguageRepository implementations."""

import pytest

from ugc_bot.domain.entities import Language
from ugc_bot.infrastructure.memory_repositories import MemoryLanguageRepository


@pytest.fixture()
def repo() -> MemoryLanguageRepository:
    ru = Language(code="ru", name_native="Русский", enabled=True)
    en = Language(code="en", name_native="English", enabled=True)
    disabled = Language(code="xx", name_native="Disabled", enabled=False)
    return MemoryLanguageRepository(
        languages={"ru": ru, "en": en, "xx": disabled}
    )


@pytest.mark.asyncio()
async def test_list_enabled_returns_only_enabled(repo):
    result = await repo.list_enabled()
    codes = {lang.code for lang in result}
    assert codes == {"ru", "en"}


@pytest.mark.asyncio()
async def test_get_by_code_found(repo):
    result = await repo.get_by_code("ru")
    assert result is not None
    assert result.name_native == "Русский"


@pytest.mark.asyncio()
async def test_get_by_code_not_found(repo):
    result = await repo.get_by_code("zz")
    assert result is None


@pytest.mark.asyncio()
async def test_get_by_code_disabled_returns_entity(repo):
    result = await repo.get_by_code("xx")
    assert result is not None
    assert result.enabled is False
