"""Private Mini App directory for creators invited by the current manager."""

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import Row

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.enums import UserStatus
from ugc_bot.domain.social import (
    SOCIAL_PLATFORM_LABELS,
    SocialPlatform,
    normalize_social_url,
)
from ugc_bot.infrastructure.db.repositories.manager_creator_directory import (
    InstagramFilter,
    invited_creator_card,
    invited_creator_followup_page,
    postpone_creator_followup,
)
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.native_caller_errors import NoStoreManagerDirectoryRoute
from ugc_bot.miniapp.principal import SignedMiniAppRequest

PAGE_SIZE = 20


class DirectoryRequest(SignedMiniAppRequest):
    bot_unavailable: bool = Field(default=False, strict=True)
    page: int = Field(default=0, ge=0, le=100000, strict=True)
    q: str = Field(default="", max_length=120, strict=True)
    instagram: InstagramFilter = "all"


class InvitedCreator(BaseModel):
    creator_id: UUID
    name: str
    city: str
    status: UserStatus
    instagram_verified: bool
    telegram_url: str | None
    followup_due: bool
    remind_at: datetime | None


class CreatorPage(BaseModel):
    creators: list[InvitedCreator]
    has_more: bool
    followup_count: int


class SocialLink(BaseModel):
    label: str
    url: str


class CreatorCard(InvitedCreator):
    links: list[SocialLink]


class FollowupRequest(SignedMiniAppRequest):
    action: Literal["contacted", "tomorrow"]


class FollowupResult(BaseModel):
    remind_at: datetime


def _creator_fields(row: Row) -> dict:
    user, profile = row[0], row[1]
    handle = (user.telegram or "").strip().removeprefix("@")
    return {
        "creator_id": user.user_id,
        "name": user.username.strip() or (user.telegram or "").strip(),
        "city": (profile.city or "").strip(),
        "status": row.status,
        "instagram_verified": row.instagram_verified,
        "telegram_url": (
            f"https://t.me/{handle}"
            if re.fullmatch(r"[A-Za-z0-9_]{5,32}", handle)
            else None
        ),
        "followup_due": row.followup_due,
        "remind_at": None if row.instagram_verified else row.remind_at,
    }


def _social_link(
    platform: SocialPlatform, value: str, name: str | None = None
) -> SocialLink | None:
    try:
        url, handle = normalize_social_url(platform, value, platform_name=name)
    except ValueError:
        return None
    return SocialLink(
        label=SOCIAL_PLATFORM_LABELS.get(platform, handle), url=url
    )


def _creator_links(rows: Sequence[Row]) -> list[SocialLink]:
    links = []
    profile = rows[0][1]
    instagram = _social_link(SocialPlatform.INSTAGRAM, profile.instagram_url)
    if instagram:
        links.append(instagram)
    for row in rows:
        if (
            not row.social_platform
            or row.social_platform == SocialPlatform.INSTAGRAM
        ):
            continue
        try:
            network = SocialPlatform(row.social_platform)
        except ValueError:
            continue
        link = _social_link(network, row.social_url, row.social_handle)
        if link is not None:
            links.append(link)
    return links


async def _context(
    request: Request,
    body: SignedMiniAppRequest,
    resolve_principal: FinancialPrincipalResolver,
):
    if request.query_params:
        raise HTTPException(422, "manager_directory_invalid")
    principal = await resolve_principal(
        request, body.init_data, platform=body.platform
    )
    if (
        not isinstance(principal, AuthenticatedMessengerPrincipal)
        or principal.platform != body.platform
    ):
        raise HTTPException(401, "financial_session_invalid")
    dispatcher = request.app.state.dispatcher
    roles = dispatcher.get("user_role_service")
    managers = dispatcher.get("manager_service")
    transactions = dispatcher.get("transaction_manager")
    if roles is None or managers is None or transactions is None:
        raise HTTPException(503, "manager_directory_unavailable")
    actor = await roles.get_user_by_id(principal.user_id)
    applications = dispatcher.get("manager_applications")
    if actor is None or not (
        actor.admin
        or await managers.is_manager(principal.user_id)
        or (
            applications is not None
            and await applications.approved(principal.user_id)
        )
    ):
        raise HTTPException(403, "manager_required")
    return principal, transactions


def create_manager_directory_router(
    resolve_principal: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/manager/invited-creators",
        route_class=NoStoreManagerDirectoryRoute,
    )

    @router.post("")
    async def creators(request: Request, body: DirectoryRequest) -> CreatorPage:
        principal, transactions = await _context(
            request, body, resolve_principal
        )
        async with transactions.transaction() as session:
            rows, followup_count = await invited_creator_followup_page(
                session,
                principal,
                bot_unavailable=body.bot_unavailable,
                offset=body.page * PAGE_SIZE,
                limit=PAGE_SIZE,
                q=body.q,
                instagram=body.instagram,
            )
        return CreatorPage(
            creators=[
                InvitedCreator(**_creator_fields(row))
                for row in rows[:PAGE_SIZE]
            ],
            has_more=len(rows) > PAGE_SIZE,
            followup_count=followup_count,
        )

    @router.post("/{creator_id}")
    async def card(
        request: Request,
        creator_id: UUID,
        body: SignedMiniAppRequest,
    ) -> CreatorCard:
        principal, transactions = await _context(
            request, body, resolve_principal
        )
        async with transactions.transaction() as session:
            rows = await invited_creator_card(session, principal, creator_id)
        if not rows:
            raise HTTPException(404, "creator_not_found")
        return CreatorCard(
            **_creator_fields(rows[0]),
            links=_creator_links(rows),
        )

    @router.post("/{creator_id}/followup")
    async def followup(
        request: Request, creator_id: UUID, body: FollowupRequest
    ) -> FollowupResult:
        principal, transactions = await _context(
            request, body, resolve_principal
        )
        delay = timedelta(days=2 if body.action == "contacted" else 1)
        async with transactions.transaction() as session:
            remind_at = await postpone_creator_followup(
                session, principal, creator_id, delay
            )
        if remind_at is None:
            raise HTTPException(404, "creator_not_found")
        return FollowupResult(remind_at=remind_at)

    return router
