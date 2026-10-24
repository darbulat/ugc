"""Dormant existing-only identity adapter, with no router or account writes."""

from collections.abc import Awaitable
from types import MappingProxyType
from typing import Protocol

from fastapi import HTTPException, Request

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
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
