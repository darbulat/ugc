"""Strict signed-request envelope shared by new Mini App capabilities."""

from collections.abc import Awaitable
from time import time
from typing import Literal, Protocol
from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict

Platform = Literal["telegram", "max"]


class PrincipalResolver(Protocol):
    def __call__(
        self, request: Request, init_data: str, *, platform: Platform
    ) -> Awaitable[UUID]: ...


class SignedMiniAppRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    init_data: str
    platform: Platform = "telegram"


def require_recent_init_data(init_data: str, *, now: float) -> None:
    """Private capabilities use a24h session and allow60s clock skew.

    This freshness check supplements HMAC validation; it never replaces it.
    Telegram documents auth_date freshness checks at
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if len(init_data) > 16384:
        raise HTTPException(status_code=401, detail="Invalid Mini App session")
    fields = parse_qsl(init_data, keep_blank_values=True)
    values = dict(fields)
    if len(fields) != len(values):
        raise HTTPException(
            status_code=401, detail="Ambiguous Mini App session"
        )
    auth_date = values.get("auth_date", "")
    if not (auth_date.isascii() and auth_date.isdigit()) or len(auth_date) > 12:
        raise HTTPException(
            status_code=401, detail="Invalid Mini App auth_date"
        )
    age = now - int(auth_date)
    if age > 86400 or age < -60:
        raise HTTPException(
            status_code=401,
            detail="Mini App session expired. Reopen the app.",
        )


def with_recent_init_data(resolver: PrincipalResolver) -> PrincipalResolver:
    async def resolve(
        request: Request, init_data: str, *, platform: Platform
    ) -> UUID:
        require_recent_init_data(init_data, now=time())
        return await resolver(request, init_data, platform=platform)

    return resolve


def require_messenger_link_init_data(init_data: str, *, now: float) -> None:
    """Require fresh consent without changing other capabilities."""
    require_recent_init_data(init_data, now=now)
    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    if now - int(fields["auth_date"]) > 3600:
        raise HTTPException(
            status_code=401, detail="Reopen MAX to link accounts"
        )
