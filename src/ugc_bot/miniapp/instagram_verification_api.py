"""Read-only Instagram verification feedback for existing Mini App users."""

from fastapi import APIRouter, HTTPException, Request

from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.principal import SignedMiniAppRequest
from ugc_bot.miniapp.social_errors import NoStoreSocialRoute


def create_instagram_verification_router(
    resolve_principal: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/blogger/instagram-verification", route_class=NoStoreSocialRoute
    )

    @router.post("/status")
    async def status(request: Request, body: SignedMiniAppRequest) -> dict:
        if request.query_params:
            raise HTTPException(422, "social_request_invalid")
        principal = await resolve_principal(
            request, body.init_data, platform=body.platform
        )
        dispatcher = request.app.state.dispatcher
        profile = await dispatcher["profile_service"].get_blogger_profile(
            principal.user_id
        )
        # Recheck the native binding after reading: an archived or remapped
        # account must not be recreated or expose the old owner's status.
        user = await dispatcher["user_role_service"].get_user(
            principal.external_id,
            MessengerType.TELEGRAM
            if body.platform == "telegram"
            else MessengerType.MAX,
        )
        if (
            user is None
            or user.user_id != principal.user_id
            or user.status != UserStatus.ACTIVE
            or getattr(
                user, "telegram_id" if body.platform == "telegram" else "max_id"
            )
            != principal.external_id
        ):
            raise HTTPException(403, "social_account_unavailable")
        if profile is None:
            raise HTTPException(400, "social_creator_profile_required")
        if profile.user_id != principal.user_id:
            raise HTTPException(403, "social_account_unavailable")
        return {
            "user_id": str(principal.user_id),
            "instagram_url": profile.instagram_url,
            "confirmed": profile.confirmed,
            "agreement_confirmed": profile.agreement_confirmed_at is not None,
        }

    return router
