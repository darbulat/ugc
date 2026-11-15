"""Create and copy a private creator link from the order workspace."""

import asyncio
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from ugc_bot.admin.auth import admin_login_redirect
from ugc_bot.domain.order_display import public_order_number
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.models import OrderItemModel
from ugc_bot.infrastructure.db.repositories.creator_invites import (
    create_invite,
    free_positions,
    matching_creator_profiles,
    order_for_invite,
    team,
)
from ugc_bot.infrastructure.db.repositories.invite_preview import (
    PREVIEW_CONSENT,
)

ERRORS = {
    "creator_invite_telegram_invalid": "Укажите корректный Telegram-ник.",
    "creator_invite_already_interested": (
        "Этот креатор уже добавлен к другой позиции."
    ),
    "invite_instagram_invalid": "Укажите ник или ссылку на профиль Instagram.",
    "creator_invite_profile_conflict": (
        "Этот профиль нельзя назначить на заказ."
    ),
    "creator_invite_position_unavailable": (
        "Позиция уже недоступна. Выберите другую."
    ),
    "creator_invite_manager_unavailable": (
        "Выберите активного менеджера из команды заказа."
    ),
}


def register_creator_invites(  # noqa: C901
    app, auth, engine, templates, require_action_token, config
):
    bot = config.bot.bot_username.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", bot):
        bot = ""

    def load(
        order_id,
        item_id,
        manager_id,
        instagram,
        create,
        telegram,
        consent_source,
        creator_name,
    ):
        with Session(engine) as db, db.begin():
            if db.get_bind().dialect.name != "postgresql":
                return None
            order = order_for_invite(db, order_id)
            if order is None:
                return None
            link, error = None, None
            if create:
                try:
                    identity = create_invite(
                        db,
                        order_id,
                        item_id,
                        manager_id,
                        instagram,
                        datetime.now(timezone.utc),
                        telegram=telegram,
                        consent_source=consent_source,
                        creator_name=creator_name,
                    )
                    link = f"https://t.me/{bot}?start=oi_{identity.hex}"
                except ValueError as exc:
                    error = ERRORS.get(
                        str(exc), "Не удалось создать приглашение."
                    )
            known = None
            if instagram:
                try:
                    matches = matching_creator_profiles(db, instagram, telegram)
                    known = (
                        "Подтверждённый профиль из базы"
                        if matches
                        else "Нужна регистрация в боте"
                    )
                except ValueError as exc:
                    known = ERRORS.get(str(exc), "Проверьте контакты.")
            now = datetime.now(timezone.utc)
            pending = (
                select(func.count())
                .where(
                    INVITES.c.item_id == OrderItemModel.paid_item_id,
                    INVITES.c.consented_at.is_(None),
                    INVITES.c.expires_at > now,
                )
                .scalar_subquery()
            )
            items = db.execute(
                free_positions(order_id)
                .with_only_columns(
                    OrderItemModel.paid_item_id,
                    OrderItemModel.ordinal,
                    pending.label("pending_invites"),
                )
                .order_by(pending, OrderItemModel.ordinal)
            ).all()
            invites = (
                db.execute(
                    select(INVITES, OrderItemModel.ordinal)
                    .join(
                        OrderItemModel,
                        OrderItemModel.paid_item_id == INVITES.c.item_id,
                    )
                    .where(INVITES.c.order_id == order_id)
                    .order_by(INVITES.c.expires_at.desc())
                    .limit(50)
                )
                .mappings()
                .all()
            )
            return dict(
                order_id=order_id,
                title=public_order_number(order_id),
                items=items,
                managers=db.execute(team(order)).all(),
                link=link,
                error=error,
                preview=order.complimentary,
                preview_consent=PREVIEW_CONSENT,
                bot=bot,
                invites=invites,
                now=now,
                known=known,
                instagram=instagram,
                telegram=telegram,
                creator_name=creator_name,
                consent_source=consent_source,
                item_id=item_id,
                manager_id=manager_id,
            )

    @app.api_route(
        "/admin/orders/{order_id}/creator-invites",
        methods=["GET", "POST"],
        response_class=HTMLResponse,
    )
    async def admin_creator_invites(request: Request, order_id: UUID):
        if not await auth.authenticate(request):
            return admin_login_redirect(request)
        item_id, manager_id, instagram = None, None, ""
        telegram = consent_source = creator_name = ""
        if request.method == "GET":
            instagram = request.query_params.get("instagram", "")[:250]
            telegram = request.query_params.get("telegram", "")[:100]
        posted = request.method == "POST"
        create = posted
        if posted:
            await require_action_token(request)
            if (
                not bot
                or not config.financial.core_enabled
                or not config.order.customer_workflows_enabled
            ):
                raise HTTPException(503, "Приглашения пока недоступны.")
            form = await request.form()
            create = form.get("operation") != "preview"
            try:
                item_id = UUID(str(form.get("item_id", "")))
                manager_id = (
                    UUID(str(form["manager_id"]))
                    if form.get("manager_id")
                    else None
                )
                instagram = str(form.get("instagram", ""))[:250]
                telegram = str(form.get("telegram", ""))[:100]
                creator_name = str(form.get("creator_name", "")).strip()[:80]
                if form.get("record_consent") == "1":
                    consent_source = str(form.get("consent_source", ""))
                    if create and consent_source not in {
                        "instagram",
                        "telegram",
                        "other",
                    }:
                        raise ValueError("Укажите источник согласия.")

            except ValueError as exc:
                raise HTTPException(
                    422, "Проверьте выбранную позицию."
                ) from exc
        data = await asyncio.to_thread(
            load,
            order_id,
            item_id,
            manager_id,
            instagram,
            create,
            telegram,
            consent_source,
            creator_name,
        )
        if data is None:
            raise HTTPException(404, "Нужен активный оплаченный заказ.")
        data["enabled"] = bool(
            bot
            and config.financial.core_enabled
            and config.order.customer_workflows_enabled
        )
        return templates.TemplateResponse(
            request,
            "creator_invites.html",
            data,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
            },
        )
