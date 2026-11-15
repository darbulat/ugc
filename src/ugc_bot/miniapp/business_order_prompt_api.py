"""Private, read-only projection for the Telegram order clipboard."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from ugc_bot.application.services.business_order_prompt import (
    render_business_order_prompt,
)
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from ugc_bot.infrastructure.db.repositories.order_notice_details import (
    SqlAlchemyOrderNoticeDetailsRepository,
)
from ugc_bot.miniapp.financial_principal import resolve_financial_principal
from ugc_bot.miniapp.native_caller_errors import (
    SHARED_CODES,
    _NativeCallerRoute,
)
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class BusinessOrderPromptRoute(_NativeCallerRoute):
    prefix = "business_order_prompt"
    codes = SHARED_CODES | {
        "business_order_prompt_forbidden": 403,
        "business_order_prompt_not_found": 404,
        "business_order_prompt_unavailable": 503,
    }
    http_pairs = {(code, status): status for code, status in codes.items()}


class BusinessOrderPromptRequest(SignedMiniAppRequest):
    platform: Literal["telegram"] = "telegram"
    order_id: UUID


router = APIRouter(route_class=BusinessOrderPromptRoute)


@router.post("/orders/gpt-copy")
async def business_order_prompt(
    request: Request, body: BusinessOrderPromptRequest
) -> dict[str, str]:
    if request.query_params:
        raise HTTPException(422, "business_order_prompt_request_invalid")
    principal = await resolve_financial_principal(
        request, body.init_data, platform=body.platform
    )
    allowed = request.app.state.config.admin.business_order_telegram_recipients
    if principal.external_id not in allowed:
        raise HTTPException(403, "business_order_prompt_forbidden")
    dispatcher = request.app.state.dispatcher
    container = dispatcher.get("container")
    if container is None or container.transaction_manager is None:
        raise HTTPException(503, "business_order_prompt_unavailable")
    repos = container.build_repos()
    async with container.transaction_manager.transaction() as session:
        actor = await repos["user_repo"].get_by_id(
            principal.user_id, session=session
        )
        if (
            actor is None
            or actor.telegram_id != principal.external_id
            or actor.messenger_type != MessengerType.TELEGRAM
            or not actor.admin
            or actor.status != UserStatus.ACTIVE
        ):
            raise HTTPException(403, "business_order_prompt_forbidden")
        order = await repos["order_repo"].get_by_id(
            body.order_id, session=session
        )
        if order is None or order.status == OrderStatus.DELETED:
            raise HTTPException(404, "business_order_prompt_not_found")
        advertiser = await repos["user_repo"].get_by_id(
            order.advertiser_id, session=session
        )
        profile = await repos["advertiser_repo"].get_by_user_id(
            order.advertiser_id, session=session
        )
        payment = await repos["payment_repo"].get_by_order(
            order.order_id, session=session
        )
        quote = await SqlAlchemyOrderNoticeDetailsRepository().load(
            order.order_id, session=session
        )
        platforms = (
            await repos["order_intake_repo"].target_platforms_for_order(
                order.order_id, session=session
            )
            if order.financial_version
            else ()
        )
    return {
        "prompt": render_business_order_prompt(
            order,
            advertiser=advertiser,
            profile=profile,
            quote=quote,
            payment=payment,
            platforms=platforms,
        )
    }
