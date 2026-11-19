"""Small authenticated search results for the manual creator form."""

import asyncio
import re
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from ugc_bot.domain.creator_invites import instagram_handle
from ugc_bot.infrastructure.db.manager_application_models import APPLICATIONS
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    InstagramStatsModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.creator_invites import (
    creator_availability,
    order_for_invite,
)
from ugc_bot.infrastructure.db.repositories.invite_partners import (
    admin_managers,
    profile_referrer,
    referrer_choices,
)

LIMIT = 8


def _rows():
    return (
        select(
            UserModel.user_id,
            UserModel.username,
            UserModel.telegram,
            UserModel.telegram_id,
            APPLICATIONS.c.answers["name"].as_string().label("manager_name"),
            APPLICATIONS.c.instagram.label("manager_instagram"),
            InstagramStatsModel.full_name,
            BloggerProfileModel.instagram_url,
        )
        .outerjoin(APPLICATIONS, APPLICATIONS.c.user_id == UserModel.user_id)
        .outerjoin(
            BloggerProfileModel,
            BloggerProfileModel.user_id == UserModel.user_id,
        )
        .outerjoin(
            InstagramStatsModel,
            InstagramStatsModel.user_id == UserModel.user_id,
        )
    )


def _human_name(value):
    value = (value or "").strip()
    if not value or value.isdecimal():
        return ""
    try:
        UUID(value)
        return ""
    except ValueError:
        return value


def person(row):
    if row is None:
        return None
    instagram = row.get("instagram_url") or row.get("manager_instagram") or ""
    try:
        instagram = instagram_handle(instagram)
    except ValueError:
        instagram = ""
    telegram = (row["telegram"] or "").strip().lstrip("@")
    name = next(
        (
            label
            for field in ("manager_name", "full_name", "username")
            if (label := _human_name(row.get(field)))
        ),
        "",
    )
    label = name or (f"@{telegram}" if telegram else "")
    label = label or (f"@{instagram}" if instagram else "Аккаунт без имени")
    details = []
    if telegram:
        details.append(f"Telegram · @{telegram}")
    if instagram:
        details.append(f"Instagram · @{instagram}")
    if not details:
        # An actionable account discriminator, never an internal UUID.
        details.append(
            f"Telegram ID · {row['telegram_id']}"
            if row.get("telegram_id") and row["telegram_id"].isdecimal()
            else "Контакты в профиле не указаны"
        )
    return dict(
        id=str(row["user_id"]),
        name=label,
        detail=" · ".join(details),
        instagram=instagram,
        telegram=telegram,
        creator_name=name or label,
    )


def selected_person(db, identity):
    if identity is None:
        return None
    return person(
        db.execute(_rows().where(UserModel.user_id == identity))
        .mappings()
        .one_or_none()
    )


def _query_words(query):
    query = query.strip()[:100]
    query = re.sub(
        r"^(?:https?://)?(?:www\.)?(?:instagram\.com|t\.me)/",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = query.split("?", 1)[0].split("#", 1)[0]
    return [
        word.lstrip("@")
        for word in query.strip("/").split()[:5]
        if word.lstrip("@")
    ]


def search_people(db, order, kind, query):
    words = _query_words(query)
    if not words:
        return dict(results=[], more=False)
    statement = _rows()
    if kind == "manager":
        statement = statement.where(
            UserModel.user_id.in_(
                admin_managers(order).with_only_columns(UserModel.user_id)
            )
        )
    elif kind == "referrer":
        statement = statement.where(
            UserModel.user_id.in_(
                referrer_choices().with_only_columns(UserModel.user_id)
            )
        )
    else:
        statement = statement.where(
            BloggerProfileModel.user_id.is_not(None),
            UserModel.status.not_in(("deleted", "blocked")),
            UserModel.user_id != order.advertiser_id,
        )
    fields = (
        UserModel.username,
        UserModel.telegram,
        APPLICATIONS.c.answers["name"].as_string(),
        APPLICATIONS.c.instagram,
        InstagramStatsModel.full_name,
        BloggerProfileModel.instagram_url,
    )
    for word in words:
        statement = statement.where(
            or_(*(field.icontains(word, autoescape=True) for field in fields))
        )
    # Prefer exact handles and names; use stable ordering for equal matches.
    term = " ".join(words).lower()
    exact = or_(*(func.lower(field) == term for field in fields))
    rows = (
        db.execute(
            statement.order_by(
                case((exact, 0), else_=1), UserModel.username, UserModel.user_id
            ).limit(LIMIT + 1)
        )
        .mappings()
        .all()
    )
    return dict(
        results=[person(row) for row in rows[:LIMIT]], more=len(rows) > LIMIT
    )


def _read(engine, order_id, callback):
    with Session(engine) as db:
        if db.get_bind().dialect.name != "postgresql":
            raise HTTPException(404)
        order = order_for_invite(db, order_id)
        if order is None:
            raise HTTPException(404, "Нужен активный оплаченный заказ.")
        return callback(db, order)


def register_invite_directory(app, auth, engine):

    @app.get("/admin/orders/{order_id}/creator-invites/search")
    async def admin_invite_search(request: Request, order_id: UUID):
        if not await auth.authenticate(request):
            raise HTTPException(401)
        kind = request.query_params.get("kind", "creator")
        if kind not in {"creator", "manager", "referrer"}:
            raise HTTPException(422)
        query = request.query_params.get("q", "")[:100]
        result = await asyncio.to_thread(
            _read,
            engine,
            order_id,
            lambda db, order: search_people(db, order, kind, query),
        )
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/admin/orders/{order_id}/creator-invites/profile")
    async def admin_invite_profile(request: Request, order_id: UUID):
        if not await auth.authenticate(request):
            raise HTTPException(401)
        instagram = request.query_params.get("instagram", "")[:250]
        telegram = request.query_params.get("telegram", "")[:100]

        def profile(db, order):
            try:
                availability = creator_availability(db, instagram, telegram)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            referrer = profile_referrer(db, order_id, instagram, telegram)
            return dict(
                availability=availability,
                referrer=selected_person(db, referrer["user_id"])
                if referrer
                else None,
            )

        result = await asyncio.to_thread(_read, engine, order_id, profile)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
