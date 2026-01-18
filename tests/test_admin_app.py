"""Tests for admin app setup."""

from __future__ import annotations

from fastapi import FastAPI

from ugc_bot.admin.app import create_admin_app


def test_create_admin_app() -> None:
    """Ensure admin app is created and mounted."""

    app = create_admin_app()
    assert isinstance(app, FastAPI)
    assert any(getattr(route, "path", "") == "/admin" for route in app.routes)
