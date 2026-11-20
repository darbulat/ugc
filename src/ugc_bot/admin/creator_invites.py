"""Create and copy a private creator link from the order workspace."""

import asyncio
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from ugc_bot.admin.auth import admin_login_redirect
from ugc_bot.admin.invite_directory import (
    register_invite_directory,
    selected_person,
)
from ugc_bot.application.services.invite_handoff_notices import (
    dispatch_customer_contact,
    dispatch_invite,
)
from ugc_bot.domain.order_display import public_order_number
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.invite_handoff_models import NOTICES, VISITS
from ugc_bot.infrastructure.db.models import OrderItemModel
from ugc_bot.infrastructure.db.repositories.creator_invites import (
    available_positions,
    create_invite,
    creator_availability,
    order_for_invite,
)
from ugc_bot.infrastructure.db.repositories.invite_partners import (
    ensure_work_manager,
    lock_invite_people,
    profile_referrer,
    save_partner,
)
from ugc_bot.infrastructure.db.repositories.invite_partners import (
    installed as partners_installed,
)
from ugc_bot.infrastructure.db.repositories.invite_preview import (
    PREVIEW_CONSENT,
)

AVAILABILITY = {
    "ready": "Подтверждённый профиль из базы · бот доступен",
    "external": "Профиль не найден · можно создать ссылку",
    "unverified": "Анкета в базе · нужно подтвердить Instagram",
    "blocked": "Профиль из базы · бот заблокирован",
    "unavailable": "Профиль из базы · отправка в бот недоступна",
}
ERRORS = {
    "creator_invite_direct_unavailable": (
        "Проверьте профиль заново. Отправка в бот недоступна."
    ),
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
        "Выберите активного менеджера из базы."
    ),
    "creator_invite_referrer_invalid": (
        "Выберите активного партнёра. "
        "Креатор не может быть собственным реферером."
    ),
    "creator_invite_partner_unavailable": (
        "Привязка партнёра пока недоступна. Обновите страницу."
    ),
}


def _consent(form, operation):
    source, error = "", None
    recorded = form.get("record_consent") == "1"
    if recorded:
        source = str(form.get("consent_source", ""))
        if operation != "preview" and source not in {
            "instagram",
            "telegram",
            "other",
        }:
            error = "Укажите, где получено согласие креатора."
        operation = "create" if operation == "send" else operation
    if operation == "send_customer" and not (recorded or form.get("invite_id")):
        error = "Подтвердите согласие креатора в переписке."
    return source, error, operation


def _sent_contact(db, order_id, receipt_id):
    if receipt_id is None:
        return None
    return (
        db.execute(
            select(
                INVITES.c.creator_name,
                INVITES.c.instagram,
                OrderItemModel.ordinal,
            )
            .join(
                OrderItemModel, OrderItemModel.paid_item_id == INVITES.c.item_id
            )
            .join(NOTICES, NOTICES.c.invite_id == INVITES.c.id)
            .where(
                INVITES.c.order_id == order_id,
                INVITES.c.id == receipt_id,
                NOTICES.c.kind == "customer",
                NOTICES.c.state == "sent",
                INVITES.c.reported_at.is_not(None),
            )
        )
        .mappings()
        .one_or_none()
    )


def register_creator_invites(  # noqa: C901
    app,
    auth,
    engine,
    templates,
    require_action_token,
    config,
    transactions=None,
):
    register_invite_directory(app, auth, engine)
    bot = config.bot.bot_username.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", bot):
        bot = ""

    def load(
        order_id,
        item_id,
        manager_id,
        instagram,
        operation,
        telegram,
        consent_source,
        creator_name,
        invite_id=None,
        receipt_id=None,
        referrer_id=None,
    ):
        with Session(engine) as db, db.begin():
            if db.get_bind().dialect.name != "postgresql":
                return None
            order = order_for_invite(db, order_id)
            if order is None:
                return None
            link, error, identity = None, None, None
            if operation == "send_customer" and invite_id:
                identity = db.scalar(
                    select(INVITES.c.id).where(
                        INVITES.c.id == invite_id,
                        INVITES.c.order_id == order_id,
                        INVITES.c.reported_at.is_not(None),
                        INVITES.c.consented_at.is_(None),
                    )
                )
                if identity is None:
                    error = "Контакт недоступен. Обновите страницу заказа."
            elif operation in {"create", "send", "send_customer"}:
                try:
                    with db.begin_nested():
                        at = datetime.now(timezone.utc)
                        lock_invite_people(
                            db, instagram, telegram, manager_id, referrer_id
                        )
                        ensure_work_manager(db, order, manager_id, at)
                        identity = create_invite(
                            db,
                            order_id,
                            item_id,
                            manager_id,
                            instagram,
                            at,
                            telegram=telegram,
                            consent_source=consent_source,
                            creator_name=creator_name,
                            direct=operation == "send",
                        )
                        save_partner(
                            db,
                            identity,
                            referrer_id,
                            at,
                            f"admin:{config.admin.admin_username}",
                        )
                    link = f"https://t.me/{bot}?start=oi_{identity.hex}"
                except ValueError as exc:
                    identity = None
                    error = ERRORS.get(
                        str(exc), "Не удалось создать приглашение."
                    )
            known, availability = None, None
            if instagram:
                try:
                    availability = creator_availability(db, instagram, telegram)
                    known = AVAILABILITY[availability]
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
                available_positions(order_id, now)
                .with_only_columns(
                    OrderItemModel.paid_item_id,
                    OrderItemModel.ordinal,
                    pending.label("pending_invites"),
                )
                .order_by(pending, OrderItemModel.ordinal)
            ).all()
            invites = (
                db.execute(
                    select(
                        INVITES,
                        OrderItemModel.ordinal,
                        exists()
                        .where(VISITS.c.invite_id == INVITES.c.id)
                        .label("opened"),
                        select(NOTICES.c.state)
                        .where(
                            NOTICES.c.invite_id == INVITES.c.id,
                            NOTICES.c.kind == "creator",
                        )
                        .scalar_subquery()
                        .label("notice_state"),
                        select(NOTICES.c.state)
                        .where(
                            NOTICES.c.invite_id == INVITES.c.id,
                            NOTICES.c.kind == "customer",
                        )
                        .scalar_subquery()
                        .label("customer_state"),
                    )
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
            referrer = (
                profile_referrer(db, order_id, instagram, telegram)
                if instagram
                else None
            )
            return dict(
                order_id=order_id,
                title=public_order_number(order_id),
                needed=order.bloggers_needed,
                handoff=_sent_contact(db, order_id, receipt_id),
                items=items,
                manager=selected_person(db, manager_id),
                partners_enabled=partners_installed(db),
                selected_referrer=selected_person(
                    db, referrer.user_id if referrer else referrer_id
                ),
                referrer=referrer,
                referrer_id=referrer.user_id if referrer else referrer_id,
                link=link,
                error=error,
                preview=order.complimentary,
                preview_consent=PREVIEW_CONSENT,
                bot=bot,
                invites=invites,
                now=now,
                known=known,
                availability=availability,
                identity=identity,
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
    async def admin_creator_invites(  # noqa: C901, PLR0912
        request: Request, order_id: UUID
    ):
        if not await auth.authenticate(request):
            return admin_login_redirect(request)
        item_id, manager_id, instagram = None, None, ""
        telegram = consent_source = creator_name = ""
        receipt_id = None
        referrer_id = None
        if request.method == "GET":
            instagram = request.query_params.get("instagram", "")[:250]
            telegram = request.query_params.get("telegram", "")[:100]
            try:
                if request.query_params.get("sent"):
                    receipt_id = UUID(request.query_params["sent"])
            except ValueError:
                pass
        posted = request.method == "POST"
        operation, form_error, invite_id = "", None, None
        record_consent = False
        if posted:
            await require_action_token(request)
            if (
                not bot
                or not config.financial.core_enabled
                or not config.order.customer_workflows_enabled
            ):
                raise HTTPException(503, "Приглашения пока недоступны.")
            form = await request.form()
            operation = str(form.get("operation") or "create")
            if operation not in {"preview", "create", "send", "send_customer"}:
                form_error = "Проверьте действие."
            if operation in {"send", "send_customer"} and transactions is None:
                raise HTTPException(503, "Отправка в бот сейчас недоступна.")
            instagram = str(form.get("instagram", ""))[:250]
            telegram = str(form.get("telegram", ""))[:100]
            creator_name = str(form.get("creator_name", "")).strip()[:80]
            record_consent = form.get("record_consent") == "1"
            consent_source, consent_error, operation = _consent(form, operation)
            form_error = form_error or consent_error
            try:
                item_id = (
                    UUID(str(form["item_id"])) if form.get("item_id") else None
                )
                manager_id = (
                    UUID(str(form["manager_id"]))
                    if form.get("manager_id")
                    else None
                )
                invite_id = (
                    UUID(str(form["invite_id"]))
                    if form.get("invite_id")
                    else None
                )
                referrer_id = (
                    UUID(str(form["referrer_id"]))
                    if form.get("referrer_id")
                    else None
                )
            except ValueError:
                form_error = (
                    "Позиция, менеджер или партнёр недоступны. "
                    "Обновите страницу."
                )
        data = await asyncio.to_thread(
            load,
            order_id,
            item_id,
            manager_id,
            instagram,
            "preview" if form_error else operation,
            telegram,
            consent_source,
            creator_name,
            invite_id,
            receipt_id,
            referrer_id,
        )
        if data is None:
            raise HTTPException(404, "Нужен активный оплаченный заказ.")
        data["error"] = form_error or data["error"]
        data["record_consent"] = record_consent
        if operation == "send_customer" and data["identity"] and not form_error:
            from ugc_bot.container.creator_invite_factory import (
                build_creator_invites,
            )

            try:
                status = await dispatch_customer_contact(
                    config,
                    build_creator_invites(transactions),
                    data["identity"],
                )
            except ValueError:
                status = None
            if status == "sent":
                destination = request.url_for(
                    "admin_creator_invites", order_id=order_id
                ).include_query_params(sent=str(data["identity"]))
                return RedirectResponse(
                    destination.replace(fragment="invite-result"),
                    status_code=303,
                    headers={"Cache-Control": "no-store"},
                )
            data["status_kind"] = "danger" if status == "failed" else "warning"
            data["status"] = {
                "sending": "Отправка заказчику уже началась.",
                "unknown": (
                    "Telegram не подтвердил отправку. Проверьте чат заказчика."
                ),
                "failed": (
                    "Контакт не доставлен. Проверьте Telegram заказчика."
                ),
            }.get(status, "Отправка недоступна. Проверьте заказ.")
            data["retained_item"] = next(
                (
                    row
                    for row in data["invites"]
                    if row["id"] == data["identity"]
                ),
                None,
            )
            if data["retained_item"]:
                data["item_id"] = data["retained_item"]["item_id"]
        if operation == "send" and data["identity"]:
            from ugc_bot.container.creator_invite_factory import (
                build_creator_invites,
            )

            status = await dispatch_invite(
                config, build_creator_invites(transactions), data["identity"]
            )
            data["status"] = {
                "sent": "Приглашение отправлено в Telegram.",
                "sending": "Отправка уже началась.",
                "unknown": "Telegram не подтвердил отправку. Повтор отключён.",
            }.get(
                status,
                "Бот не смог отправить приглашение. Ссылку можно скопировать.",
            )
            if status == "sent":
                data["link"] = None
        data["enabled"] = bool(
            bot
            and config.financial.core_enabled
            and config.order.customer_workflows_enabled
        )
        return templates.TemplateResponse(
            request,
            "creator_invites.html",
            data,
            status_code=422 if form_error else 200,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
            },
        )
