"""Authentication backend for SQLAdmin."""

import hashlib
import hmac

from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request


class AdminAuth(AuthenticationBackend):
    """Session-based authentication for SQLAdmin."""

    def __init__(self, secret_key: str, username: str, password: str) -> None:
        """Initialize auth backend with credentials."""

        super().__init__(secret_key=secret_key)
        self._username = username
        self._password_hash = _hash_password(password)
        self._token = _hash_password(f"{username}:{password}")

    async def login(self, request: Request) -> bool:
        """Handle admin login."""

        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", "")).strip()

        if _verify_credentials(username, password, self._username, self._password_hash):
            request.session.update({"admin_token": self._token})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        """Handle admin logout."""

        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        """Check current session."""

        return request.session.get("admin_token") == self._token


def _hash_password(value: str) -> str:
    """Hash password value using SHA256."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _verify_credentials(
    username: str,
    password: str,
    expected_username: str,
    expected_password_hash: str,
) -> bool:
    """Verify admin credentials."""

    if not hmac.compare_digest(username, expected_username):
        return False
    return hmac.compare_digest(_hash_password(password), expected_password_hash)
