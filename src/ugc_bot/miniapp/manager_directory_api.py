"""Private Mini App directory for creators invited by the current manager."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.enums import UserStatus
from ugc_bot.domain.social import (
    SOCIAL_PLATFORM_LABELS,
    SocialPlatform,
    normalize_social_url,
)
from ugc_bot.infrastructure.db.models import BloggerProfileModel, UserModel
from ugc_bot.infrastructure.db.repositories.manager_creator_directory import (
    invited_creator_card,
    invited_creator_page,
)
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.native_caller_errors import NoStoreManagerDirectoryRoute
from ugc_bot.miniapp.principal import SignedMiniAppRequest

PAGE_SIZE = 20


class DirectoryRequest(SignedMiniAppRequest):
    bot_unavailable: bool = Field(default=False, strict=True)
    page: int = Field(default=0, ge=0, le=100000, strict=True)
    q: str = Field(default="", max_length=120, strict=True)


class InvitedCreator(BaseModel):
    creator_id: UUID
    name: str
    city: str
    status: UserStatus


class CreatorPage(BaseModel):
    creators: list[InvitedCreator]
    has_more: bool


class SocialLink(BaseModel):
    label: str
    url: str


class CreatorCard(InvitedCreator):
    instagram_verified: bool
    links: list[SocialLink]


def _creator_fields(
    user: UserModel, profile: BloggerProfileModel, status: UserStatus
) -> dict:
    return {
        "creator_id": user.user_id,
        "name": user.username.strip() or (user.telegram or "").strip(),
        "city": (profile.city or "").strip(),
        "status": status,
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
            rows = await invited_creator_page(
                session,
                principal,
                bot_unavailable=body.bot_unavailable,
                offset=body.page * PAGE_SIZE,
                limit=PAGE_SIZE,
                q=body.q,
            )
        return CreatorPage(
            creators=[
                InvitedCreator(**_creator_fields(user, profile, status))
                for user, profile, status in rows[:PAGE_SIZE]
            ],
            has_more=len(rows) > PAGE_SIZE,
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
        user, profile, status, *_ = rows[0]
        links = []
        instagram = _social_link(
            SocialPlatform.INSTAGRAM, profile.instagram_url
        )
        if instagram:
            links.append(instagram)
        for _, _, _, platform, url, handle in rows:
            if not platform or platform == SocialPlatform.INSTAGRAM:
                continue
            try:
                network = SocialPlatform(platform)
            except ValueError:
                continue
            link = _social_link(network, url, handle)
            if link is not None:
                links.append(link)
        return CreatorCard(
            **_creator_fields(user, profile, status),
            instagram_verified=bool(
                profile.confirmed and (profile.instagram_user_id or "").strip()
            ),
            links=links,
        )

    return router
