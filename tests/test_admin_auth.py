"""Tests for SQLAdmin auth backend."""

from __future__ import annotations

import pytest

from ugc_bot.admin.auth import AdminAuth


class FakeRequest:
    """Minimal request stub for auth backend."""

    def __init__(self, form_data: dict[str, str]) -> None:
        self._form_data = form_data
        self.session: dict[str, str] = {}

    async def form(self) -> dict[str, str]:
        """Return fake form data."""

        return self._form_data


@pytest.mark.asyncio
async def test_auth_login_logout() -> None:
    """Login and logout flow."""

    auth = AdminAuth(secret_key="secret", username="admin", password="pass")
    request = FakeRequest({"username": "admin", "password": "pass"})

    assert await auth.login(request) is True
    assert await auth.authenticate(request) is True
    assert await auth.logout(request) is True
    assert await auth.authenticate(request) is False


@pytest.mark.asyncio
async def test_auth_rejects_invalid() -> None:
    """Reject invalid credentials."""

    auth = AdminAuth(secret_key="secret", username="admin", password="pass")
    request = FakeRequest({"username": "admin", "password": "wrong"})

    assert await auth.login(request) is False
