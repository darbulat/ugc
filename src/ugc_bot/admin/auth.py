"""Authentication backend for SQLAdmin."""

import hashlib
import hmac
from urllib.parse import unquote, urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse


def safe_admin_return_to(value: object) -> str | None:
    """Accept only local admin destinations, including encoded path checks."""
    if not isinstance(value, str):
        return None
    decoded = value
    for _ in range(3):
        decoded = unquote(decoded)
    if any(ord(char) < 32 or char == "\\" for char in decoded):
        return None
    parsed = urlsplit(decoded)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/admin/"):
        return None
    if parsed.path.rstrip("/") in {"/admin/login", "/admin/logout"}:
        return None
    return value


def admin_login_redirect(request: Request) -> RedirectResponse:
    target = safe_admin_return_to(
        request.url.path
        + ("?" + request.url.query if request.url.query else "")
    )
    if target and "session" in request.scope:
        request.session["admin_return_to"] = target
    return RedirectResponse(url="/admin/login")


def _hash_password_argon2(password: str) -> str:
    """Hash password using Argon2 (resistant to brute-force)."""

    return PasswordHasher().hash(password)


def _verify_password_argon2(password_hash: str, password: str) -> bool:
    """Verify password against Argon2 hash."""

    try:
        PasswordHasher().verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False


def _make_session_token(secret_key: str, username: str, password: str) -> str:
    """Create deterministic session token from credentials."""

    data = f"{username}:{password}".encode("utf-8")
    return hmac.new(
        secret_key.encode("utf-8"), data, hashlib.sha256
    ).hexdigest()


class AdminAuth(AuthenticationBackend):
    """Session-based authentication for SQLAdmin."""

    def __init__(self, secret_key: str, username: str, password: str) -> None:
        """Initialize auth backend with credentials."""

        super().__init__(secret_key=secret_key)
        self._username = username
        self._password_hash = _hash_password_argon2(password)
        self._token = _make_session_token(secret_key, username, password)

    async def login(self, request: Request) -> bool:
        """Handle admin login."""

        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", "")).strip()

        if _verify_credentials(
            username, password, self._username, self._password_hash
        ):
            request.session.update({"admin_token": self._token})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        """Handle admin logout."""

        request.session.clear()
        return True

    def remember_destination(self, request: Request) -> None:
        target = safe_admin_return_to(
            request.url.path
            + ("?" + request.url.query if request.url.query else "")
        )
        if target:
            request.session["admin_return_to"] = target

    def redirect_to_login(self, request: Request) -> RedirectResponse:
        return admin_login_redirect(request)

    async def authenticate(self, request: Request) -> bool:
        """Check current session (constant-time to prevent timing attacks)."""

        token = request.session.get("admin_token") or ""
        authenticated = hmac.compare_digest(token, self._token)
        if not authenticated and hasattr(request, "url"):
            self.remember_destination(request)
        return authenticated


def _verify_credentials(
    username: str,
    password: str,
    expected_username: str,
    expected_password_hash: str,
) -> bool:
    """Verify admin credentials."""

    if not hmac.compare_digest(username, expected_username):
        return False
    return _verify_password_argon2(expected_password_hash, password)
