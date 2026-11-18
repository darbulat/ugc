"""Tests for SQLAdmin auth backend."""

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
async def test_late_authenticated_response_preserves_action_token():
    from ugc_bot.admin.app import _admin_action_token, _require_action_token

    auth = AdminAuth(secret_key="secret", username="admin", password="pass")
    request = FakeRequest({"username": "admin", "password": "pass"})
    assert await auth.login(request)
    # A dashboard request can finish after the user opens the next page.
    login_snapshot = dict(request.session)
    token = _admin_action_token(request)
    late_response = FakeRequest({"csrf_token": token})
    late_response.session = login_snapshot
    assert await auth.authenticate(late_response)
    await _require_action_token(late_response)
    assert await auth.logout(request)
    assert await auth.login(request)
    assert _admin_action_token(request) != token


@pytest.mark.asyncio
async def test_auth_rejects_invalid() -> None:
    """Reject invalid credentials."""

    auth = AdminAuth(secret_key="secret", username="admin", password="pass")
    request = FakeRequest({"username": "admin", "password": "wrong"})

    assert await auth.login(request) is False


@pytest.mark.asyncio
async def test_auth_rejects_wrong_username() -> None:
    """Reject when username does not match."""

    auth = AdminAuth(secret_key="secret", username="admin", password="pass")
    request = FakeRequest({"username": "wrong_user", "password": "pass"})

    assert await auth.login(request) is False


def test_safe_admin_return_target_rejects_external_and_encoded_targets() -> (
    None
):
    from ugc_bot.admin.auth import safe_admin_return_to

    assert (
        safe_admin_return_to("/admin/order-model/edit/123?tab=settings")
        == "/admin/order-model/edit/123?tab=settings"
    )
    for target in (
        "https://evil.test/admin",
        "//evil.test/admin",
        "/admin/\\evil",
        "/admin/%5cevil",
        "/admin/%0aevil",
        "/elsewhere",
        "/admin/login",
    ):
        assert safe_admin_return_to(target) is None
