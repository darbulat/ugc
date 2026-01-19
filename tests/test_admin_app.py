"""Tests for admin app setup."""

from fastapi import FastAPI
import pytest

from ugc_bot.admin.app import create_admin_app


def test_create_admin_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure admin app is created and mounted."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db")

    app = create_admin_app()
    assert isinstance(app, FastAPI)
    assert any(getattr(route, "path", "") == "/admin" for route in app.routes)
