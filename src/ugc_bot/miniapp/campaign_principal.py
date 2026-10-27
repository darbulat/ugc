"""Existing-only campaign identity and caller-transaction native validation."""

from collections.abc import Awaitable
from types import MappingProxyType
from typing import Protocol

from fastapi import HTTPException, Request

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.miniapp.financial_principal import resolve_financial_principal
from ugc_bot.miniapp.principal import Platform

_FAILURES = MappingProxyType(
    {
        "financial_session_invalid": (401, "campaign_session_invalid"),
        "financial_unavailable": (503, "campaign_unavailable"),
        "existing_financial_account_required": (
            404,
            "existing_campaign_account_required",
        ),
        "financial_principal_changed": (403, "campaign_principal_changed"),
    }
)


class CampaignPrincipalResolver(Protocol):
    def __call__(
        self, request: Request, init_data: str, *, platform: Platform
    ) -> Awaitable[AuthenticatedMessengerPrincipal]: ...


def campaign_actor(identity, *, platform):
    """Retain UUID resolver compatibility for separately injected adapters."""
    if isinstance(identity, AuthenticatedMessengerPrincipal):
        if identity.platform != platform:
            raise HTTPException(401, "campaign_session_invalid")
        return identity.user_id
    return identity


async def verify_campaign_principal(identity, foundation, *, session):
    if not isinstance(identity, AuthenticatedMessengerPrincipal):
        return
    # The operation already opened its snapshot or acquired its User barrier.
    # A denial exits the caller transaction before staged writes commit.
    context = await foundation.context(
        identity.user_id, lock=False, session=session
    )
    actor = context["actor"]
    try:
        require_current_principal(
            identity,
            identity.user_id,
            actor["user_id"],
            actor.get("telegram_id"),
            actor.get("max_id"),
        )
    except ValueError:
        raise PermissionError("campaign_principal_changed") from None


async def resolve_campaign_principal(
    request: Request, init_data: str, *, platform: Platform
) -> AuthenticatedMessengerPrincipal:
    if platform not in ("telegram", "max"):
        raise HTTPException(401, "campaign_session_invalid")
    try:
        principal = await resolve_financial_principal(
            request, init_data, platform=platform
        )
    except HTTPException as error:
        status, code = (
            _FAILURES.get(error.detail, (503, "campaign_unavailable"))
            if isinstance(error.detail, str)
            else (503, "campaign_unavailable")
        )
        raise HTTPException(status, code) from None
    except Exception:
        raise HTTPException(503, "campaign_unavailable") from None
    if (
        not isinstance(principal, AuthenticatedMessengerPrincipal)
        or principal.platform != platform
    ):
        raise HTTPException(401, "campaign_session_invalid")
    return principal
