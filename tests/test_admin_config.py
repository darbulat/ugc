"""Tests for admin config helpers."""

from __future__ import annotations

import pytest

from ugc_bot.admin.config import build_async_database_url


def test_build_async_database_url_converts_driver() -> None:
    """Convert sync postgres driver to async."""

    url = build_async_database_url("postgresql+psycopg://user:pass@localhost:5432/db")
    assert url.startswith("postgresql+asyncpg://")


def test_build_async_database_url_override() -> None:
    """Use override URL when provided."""

    url = build_async_database_url(
        "postgresql+psycopg://user:pass@localhost:5432/db",
        "postgresql://user:pass@localhost:5432/other",
    )
    assert url.startswith("postgresql+asyncpg://")
    assert "other" in url


def test_build_async_database_url_requires_value() -> None:
    """Require a URL."""

    with pytest.raises(ValueError):
        build_async_database_url("")
