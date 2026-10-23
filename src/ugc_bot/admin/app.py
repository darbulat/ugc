"""SQLAdmin application setup."""

import asyncio
import dataclasses
import logging
from enum import Enum
from pathlib import Path
from typing import Any, Optional, TypeVar, cast
from uuid import UUID

from aiogram import Bot
from aiogram.types import BufferedInputFile
from fastapi import Depends, FastAPI, HTTPException
from sqladmin import Admin, BaseView, ModelView, action, expose
from sqladmin.authentication import login_required
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from wtforms import SelectField  # type: ignore[import-untyped]

from ugc_bot.admin.auth import AdminAuth
from ugc_bot.admin.dashboard_service import (
    AdminDashboardService,
    DelayThresholds,
    PeriodKey,
)
from ugc_bot.application.geography import (
    get_geometry_queries_from_spec,
    parse_geography,
)
from ugc_bot.application.ports import OrderRepository
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.geocoder import (
    wkt_multipoint_from_lat_lon,
)
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.referral_income_service import (
    ReferralIncomeService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import AppConfig, load_config
from ugc_bot.container import Container
from ugc_bot.domain.enums import (
    ComplaintStatus,
    InteractionStatus,
    OrderStatus,
    PayoutRequestStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    BloggerProfileModel,
    BloggerRatingModel,
    BotTextModel,
    ComplaintModel,
    ContactPricingModel,
    CountryModel,
    InstagramVerificationCodeModel,
    InteractionModel,
    LanguageModel,
    NpsResponseModel,
    OfferDispatchModel,
    OrderModel,
    PaymentModel,
    PayoutRequestModel,
    ReferralIncomeEntryModel,
    UserModel,
)
from ugc_bot.infrastructure.redis_cache import (
    AdminCache,
    deserialize_admin_payload,
    serialize_admin_payload,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


_admin_container: Container | None = None


def _get_admin_container() -> Container | None:
    """Return container set at app creation."""
    return _admin_container


def _get_services(
    container: Container,
) -> tuple[UserRoleService, ComplaintService, InteractionService]:
    """Get services for admin actions."""
    return container.build_admin_services()


def _get_order_moderation_deps(
    container: Container,
) -> tuple[ContentModerationService, OutboxPublisher, OrderRepository]:
    """Get ContentModerationService, OutboxPublisher, OrderRepository."""
    content_moderation = ContentModerationService()
    outbox_publisher = container.build_outbox_publisher()
    order_repo = container.build_repos()["order_repo"]
    return (content_moderation, outbox_publisher, order_repo)


async def _update_order_location_geometry_after_geography_change(
    order_id: UUID, geography_raw: Any
) -> None:
    """Resolve location_geometry from new geography and save order.

    When admin updates order geography, we need to recompute location_geometry
    via geocoder so that offer dispatch uses the correct geometry filter.
    """
    container = _get_admin_container()
    if not container:
        return
    geography_clean = (geography_raw or "").strip() or None
    new_geometry: str | None = None
    if geography_clean:
        geocoder = container.build_geocoder()
        spec = parse_geography(geography_clean)
        if spec is not None:
            queries = get_geometry_queries_from_spec(spec)
            if queries:
                new_geometry = await geocoder.get_multipolygon_wkt_for_queries(
                    queries
                )
    _, _, order_repo = _get_order_moderation_deps(container)
    tm = container.transaction_manager
    if not tm:
        return
    try:
        async with tm.transaction() as session:
            order = await order_repo.get_by_id(order_id, session=session)
            if order is None:
                return
            updated = dataclasses.replace(order, location_geometry=new_geometry)
            await order_repo.save(updated, session=session)
        logger.info(
            "Updated order location_geometry after geography change in admin",
            extra={"order_id": str(order_id)},
        )
    except Exception:
        logger.exception(
            "Failed to update order location_geometry after geography change",
            extra={"order_id": str(order_id)},
        )


async def _publish_order_activation(order_id: UUID) -> None:
    """Publish order activation event via outbox."""
    try:
        container = _get_admin_container()
        if not container:
            return
        _, outbox_publisher, order_repo = _get_order_moderation_deps(container)
        tm = container.transaction_manager
        if tm:
            async with tm.transaction() as session:
                order = await order_repo.get_by_id(order_id, session=session)
                if order:
                    await outbox_publisher.publish_order_activation(
                        order, session=session
                    )
    except Exception:
        logger.exception(
            "Failed to publish order activation after admin approval",
            extra={"order_id": str(order_id)},
        )


async def _update_order_managers(order_id: UUID, managers_raw: str) -> None:
    """Parse managers field and update manager-order assignments.

    An empty string removes all manager assignments for the order.
    """
    container = _get_admin_container()
    if not container:
        return
    manager_service = container.build_manager_service()
    usernames = [
        u.strip().lstrip("@") for u in managers_raw.split(",") if u.strip()
    ]
    await manager_service.set_managers_for_order(order_id, usernames)


async def _update_blogger_profile_location_from_nominatim(
    user_id: UUID, city: Optional[str] = None
) -> None:
    """Update blogger profile location_geometry, region, country via geocoder.

    When admin updates blogger profile city, we geocode and save coordinates,
    region and country to the profile.
    """
    container = _get_admin_container()
    if not container:
        return
    repos = container.build_repos()
    blogger_repo = repos.get("blogger_repo")
    tm = container.transaction_manager
    if not blogger_repo or not tm:
        return
    try:
        async with tm.transaction() as session:
            profile = await blogger_repo.get_by_user_id(
                user_id, session=session
            )
            if profile is None:
                return
            city_for_query = (city or "").strip() or (
                profile.city or ""
            ).strip()
            if not city_for_query:
                return
            geocoder = container.build_geocoder()
            details = await geocoder.geocode_with_details(
                city_for_query,
                region=profile.region,
                country=profile.country or None,
            )
            if details is None:
                return
            lat, lon, _, _, region_nom, country_nom = details
            new_geometry = wkt_multipoint_from_lat_lon(lat, lon)
            new_region = (
                region_nom if region_nom is not None else profile.region
            )
            new_country = (
                country_nom
                if country_nom is not None
                else (profile.country or "")
            )
            updated = dataclasses.replace(
                profile,
                location_geometry=new_geometry,
                region=new_region,
                country=new_country,
            )
            await blogger_repo.save(updated, session=session)
        logger.info(
            "Updated blogger profile location from Nominatim after city change",
            extra={"user_id": str(user_id)},
        )
    except Exception:
        logger.exception(
            "Failed to update blogger profile location from Nominatim",
            extra={"user_id": str(user_id)},
        )


T = TypeVar("T")
_DASHBOARD_PERIODS = ("today", "yesterday", "7d", "30d", "all")
_PERIOD_LABELS = {
    "today": "Сегодня",
    "yesterday": "Вчера",
    "7d": "7 дней",
    "30d": "30 дней",
    "all": "Все",
}
_STATUS_LABELS = {
    "active": "Активен",
    "completed": "Завершён",
    "archive": "Архив",
    "complaint": "Жалоба",
}
_USER_STATUS_LABELS = {
    "active": "Активен",
    "limited": "Ограничен",
}
_DELAY_REASON_LABELS = {
    "active_overdue": "Слишком долго активен",
    "no_responses": "Нет откликов",
    "low_picked": "Мало подобрано",
}


def _normalize_period(period: str) -> PeriodKey:
    """Return supported dashboard period."""
    normalized = period if period in _DASHBOARD_PERIODS else "today"
    return cast(PeriodKey, normalized)


def _build_dashboard_service(
    config: AppConfig, container: Container
) -> AdminDashboardService:
    """Build AdminDashboardService from config and container."""
    thresholds = DelayThresholds(
        active_days=config.admin.admin_delay_active_days,
        no_responses_hours=config.admin.admin_no_responses_hours,
        low_picked_hours=config.admin.admin_low_picked_hours,
        archive_days=config.admin.admin_archive_days,
    )
    referral_income_service: ReferralIncomeService | None = None
    if container.session_factory and container.transaction_manager:
        referral_income_service = container.build_referral_income_service()
    offer_dispatch_service = (
        container.build_offer_dispatch_service()
        if container.session_factory
        else None
    )
    return AdminDashboardService(
        session_factory=container.session_factory,
        timezone_name=config.admin.admin_dashboard_timezone,
        thresholds=thresholds,
        referral_income_service=referral_income_service,
        offer_dispatch_service=offer_dispatch_service,
    )


def _build_templates(app: FastAPI) -> Jinja2Templates:
    """Attach static assets and return templates instance."""
    templates = Jinja2Templates(
        directory=str(Path(__file__).parent / "templates")
    )
    app.mount(
        "/admin/mvp-static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="admin_mvp_static",
    )
    return templates


def _dashboard_cache_ttl(period: str) -> int:
    """TTL in seconds for dashboard/charts by period."""
    if period in ("today", "yesterday"):
        return 90
    if period == "all":
        return 600
    return 300


async def _get_cached_or_fetch(
    cache: AdminCache | None,
    cache_key: str | None,
    ttl: int,
    fetch_coro,
) -> dict[str, Any]:
    """Return cached payload or await fetch_coro(); then cache."""
    if cache and cache_key:
        raw = await cache.get(cache_key)
        if raw is not None:
            return cast(
                dict[str, Any],
                deserialize_admin_payload(raw),
            )
    result = await fetch_coro()
    if cache and cache_key:
        await cache.set(
            cache_key,
            serialize_admin_payload(result),
            ttl,
        )
    return result


async def _get_dashboard_payload_cached(
    dashboard_service: AdminDashboardService,
    period_key: PeriodKey,
    cache: AdminCache | None,
    use_cache: bool,
    cache_key: str | None,
    referrers_page: int = 1,
    referrers_per_page: int = 25,
    referrers_sort: str | None = None,
    referrers_order: str | None = None,
    referrers_filter: str | None = None,
    include_timings: bool = False,
) -> dict[str, Any]:
    """Load dashboard from cache or dashboard_service; set cache when used."""
    if cache and use_cache and cache_key:
        raw = await cache.get(cache_key)
        if raw is not None:
            return cast(
                dict[str, Any],
                deserialize_admin_payload(raw),
            )
    payload = await dashboard_service.get_dashboard(
        period_key,
        referrers_page=referrers_page,
        referrers_per_page=referrers_per_page,
        referrers_sort=referrers_sort,
        referrers_order=referrers_order or "desc",
        referrers_filter=referrers_filter,
        include_timings=include_timings,
    )
    if cache and use_cache and cache_key:
        await cache.set(
            cache_key,
            serialize_admin_payload(payload),
            _dashboard_cache_ttl(period_key),
        )
    return payload


def _dashboard_cache_key(
    period_key: str,
    referrers_filter: str,
    referrers_page: int,
    referrers_per_page: int,
    referrers_sort: str,
    referrers_order: str,
) -> str:
    """Build cache key for dashboard/referrers payload."""
    return (
        f"dashboard:{period_key}:{referrers_filter or 'all'}:"
        f"{referrers_page}:{referrers_per_page}:"
        f"{referrers_sort or ''}:{referrers_order}"
    )


async def _render_dashboard_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    period: str,
    referrers_page: int,
    referrers_per_page: int,
    referrers_sort: str,
    referrers_order: str,
    referrers_filter: str,
    timings: str,
):
    """Render dashboard HTML page."""
    if not await auth.authenticate(request):
        return RedirectResponse(url="/admin/login")
    period_key = _normalize_period(period)
    include_timings = (
        timings.lower() in ("1", "true", "yes") if timings else False
    )
    use_cache = bool(cache and not include_timings)
    cache_key = (
        _dashboard_cache_key(
            period_key,
            referrers_filter,
            referrers_page,
            referrers_per_page,
            referrers_sort,
            referrers_order,
        )
        if use_cache
        else None
    )
    payload = await _get_dashboard_payload_cached(
        dashboard_service,
        period_key,
        cache,
        use_cache,
        cache_key,
        referrers_page=referrers_page,
        referrers_per_page=referrers_per_page,
        referrers_sort=referrers_sort or None,
        referrers_order=referrers_order or "desc",
        referrers_filter=referrers_filter or None,
        include_timings=include_timings,
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "payload": payload,
            "period": period_key,
            "periods": _DASHBOARD_PERIODS,
            "period_labels": _PERIOD_LABELS,
            "status_labels": _STATUS_LABELS,
            "delay_reason_labels": _DELAY_REASON_LABELS,
            "referrers_sort": referrers_sort,
            "referrers_order": referrers_order,
            "referrers_filter": referrers_filter,
        },
    )


async def _render_referrers_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    period: str,
    referrers_page: int,
    referrers_per_page: int,
    referrers_sort: str,
    referrers_order: str,
    referrers_filter: str,
    timings: str,
):
    """Render referrers HTML page."""
    if not await auth.authenticate(request):
        return RedirectResponse(url="/admin/login")
    period_key = _normalize_period(period)
    include_timings = (
        timings.lower() in ("1", "true", "yes") if timings else False
    )
    use_cache = bool(cache and not include_timings)
    cache_key = (
        _dashboard_cache_key(
            period_key,
            referrers_filter,
            referrers_page,
            referrers_per_page,
            referrers_sort,
            referrers_order,
        )
        if use_cache
        else None
    )
    payload = await _get_dashboard_payload_cached(
        dashboard_service,
        period_key,
        cache,
        use_cache,
        cache_key,
        referrers_page=referrers_page,
        referrers_per_page=referrers_per_page,
        referrers_sort=referrers_sort or None,
        referrers_order=referrers_order or "desc",
        referrers_filter=referrers_filter or None,
        include_timings=include_timings,
    )
    return templates.TemplateResponse(
        request,
        "referrers.html",
        {
            "payload": payload,
            "period": period_key,
            "periods": _DASHBOARD_PERIODS,
            "period_labels": _PERIOD_LABELS,
            "referrers_sort": referrers_sort,
            "referrers_order": referrers_order,
            "referrers_filter": referrers_filter,
        },
    )


async def _render_creators_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    list_cache_ttl: int,
    period: str,
    only_new: bool,
    with_complaints: bool,
    page: int,
    per_page: int,
    q: str,
    sort: str,
    order: str,
):
    """Render creators list HTML page."""
    if not await auth.authenticate(request):
        return RedirectResponse(url="/admin/login")
    period_key = _normalize_period(period)
    cache_key = (
        f"creators:{period_key}:{only_new}:{with_complaints}:"
        f"{page}:{per_page}:{q or ''}:{sort}:{order}"
        if cache
        else None
    )

    async def _fetch():
        return await dashboard_service.list_creators(
            period=period_key,
            only_new=only_new,
            only_with_complaints=with_complaints,
            page=page,
            per_page=per_page,
            q=q or None,
            sort=sort,
            order=order,
        )

    result = await _get_cached_or_fetch(
        cache, cache_key, list_cache_ttl, _fetch
    )
    creators_by_city = await dashboard_service.get_creators_by_city()
    return templates.TemplateResponse(
        request,
        "creators.html",
        {
            "creators": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": result["total_pages"],
            "period": period_key,
            "periods": _DASHBOARD_PERIODS,
            "period_labels": _PERIOD_LABELS,
            "user_status_labels": _USER_STATUS_LABELS,
            "only_new": only_new,
            "with_complaints": with_complaints,
            "search_query": q,
            "sort": sort,
            "order": order,
            "creators_by_city": creators_by_city,
        },
    )


async def _render_advertisers_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    list_cache_ttl: int,
    page: int,
    per_page: int,
    q: str,
    sort: str,
    order: str,
):
    """Render advertisers list HTML page."""
    if not await auth.authenticate(request):
        return RedirectResponse(url="/admin/login")
    cache_key = (
        f"advertisers:{page}:{per_page}:{q or ''}:{sort}:{order}"
        if cache
        else None
    )

    async def _fetch():
        return await dashboard_service.list_advertisers(
            page=page,
            per_page=per_page,
            q=q or None,
            sort=sort,
            order=order,
        )

    result = await _get_cached_or_fetch(
        cache, cache_key, list_cache_ttl, _fetch
    )
    return templates.TemplateResponse(
        request,
        "advertisers.html",
        {
            "advertisers": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": result["total_pages"],
            "search_query": q,
            "sort": sort,
            "order": order,
        },
    )


async def _render_orders_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    list_cache_ttl: int,
    period: str,
    status: str | None,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    search: str | None = None,
):
    """Render orders list HTML page."""
    if not await auth.authenticate(request):
        return RedirectResponse(url="/admin/login")
    period_key = _normalize_period(period)
    search_term = search.strip() if search else ""
    cache_key = (
        f"orders:{period_key}:{status or ''}"
        f":{page}:{per_page}:{sort}:{order}"
        f":{search_term}"
        if cache
        else None
    )

    async def _fetch():
        return await dashboard_service.list_orders(
            period=period_key,
            status_filter=status,
            page=page,
            per_page=per_page,
            sort=sort,
            order=order,
            search=search_term or None,
        )

    result = await _get_cached_or_fetch(
        cache, cache_key, list_cache_ttl, _fetch
    )
    return templates.TemplateResponse(
        request,
        "orders.html",
        {
            "orders": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": result["total_pages"],
            "period": period_key,
            "periods": _DASHBOARD_PERIODS,
            "period_labels": _PERIOD_LABELS,
            "status_filter": status,
            "status_labels": _STATUS_LABELS,
            "sort": sort,
            "order": order,
            "search_query": search_term,
        },
    )


async def _render_order_detail_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    order_id: UUID,
):
    """Render order detail HTML page."""
    if not await auth.authenticate(request):
        return RedirectResponse(url="/admin/login")
    order = await dashboard_service.get_order_card(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    return templates.TemplateResponse(
        request,
        "order_detail.html",
        {
            "order": order,
            "status_labels": _STATUS_LABELS,
        },
    )


async def _render_user_card_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    user_id: UUID,
):
    """Render user card HTML page."""
    if not await auth.authenticate(request):
        return RedirectResponse(url="/admin/login")
    user_card = await dashboard_service.get_user_card(user_id)
    if user_card is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return templates.TemplateResponse(
        request,
        "user_card.html",
        {
            "user": user_card,
            "user_status_labels": _USER_STATUS_LABELS,
        },
    )


async def _api_dashboard_json(
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    period: str,
    timings: str,
) -> dict[str, Any]:
    """Dashboard payload as JSON."""
    period_key = _normalize_period(period)
    include_timings = (
        timings.lower() in ("1", "true", "yes") if timings else False
    )
    cache_key = (
        f"dashboard_api:{period_key}" if cache and not include_timings else None
    )
    if cache and not include_timings and cache_key:
        raw = await cache.get(cache_key)
        if raw is not None:
            return cast(
                dict[str, Any],
                deserialize_admin_payload(raw),
            )
    payload = await dashboard_service.get_dashboard(
        period_key, include_timings=include_timings
    )
    if cache and cache_key:
        await cache.set(
            cache_key,
            serialize_admin_payload(payload),
            _dashboard_cache_ttl(period_key),
        )
    return payload


async def _api_charts_json(
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    period: str,
) -> dict[str, Any]:
    """Charts payload as JSON."""
    period_key = _normalize_period(period)
    if cache:
        cache_key = f"charts:{period_key}"
        raw = await cache.get(cache_key)
        if raw is not None:
            return cast(
                dict[str, Any],
                deserialize_admin_payload(raw),
            )
    payload = await dashboard_service.get_dashboard_charts(period_key)
    if cache:
        await cache.set(
            cache_key,
            serialize_admin_payload(payload),
            _dashboard_cache_ttl(period_key),
        )
    return payload


async def _api_creators_json(
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    list_ttl: int,
    period: str,
    only_new: bool,
    with_complaints: bool,
    page: int,
    per_page: int,
    q: str,
    sort: str,
    order: str,
) -> dict[str, Any]:
    """Creators list as JSON."""
    period_key = _normalize_period(period)
    cache_key = (
        f"creators:{period_key}:{only_new}:{with_complaints}:"
        f"{page}:{per_page}:{q or ''}:{sort}:{order}"
        if cache
        else None
    )

    async def _fetch():
        return await dashboard_service.list_creators(
            period=period_key,
            only_new=only_new,
            only_with_complaints=with_complaints,
            page=page,
            per_page=per_page,
            q=q or None,
            sort=sort,
            order=order,
        )

    return await _get_cached_or_fetch(cache, cache_key, list_ttl, _fetch)


async def _api_advertisers_json(
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    list_ttl: int,
    page: int,
    per_page: int,
    q: str,
    sort: str,
    order: str,
) -> dict[str, Any]:
    """Advertisers list as JSON."""
    cache_key = (
        f"advertisers:{page}:{per_page}:{q or ''}:{sort}:{order}"
        if cache
        else None
    )

    async def _fetch():
        return await dashboard_service.list_advertisers(
            page=page,
            per_page=per_page,
            q=q or None,
            sort=sort,
            order=order,
        )

    return await _get_cached_or_fetch(cache, cache_key, list_ttl, _fetch)


async def _api_orders_json(
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    list_ttl: int,
    period: str,
    status: str | None,
    page: int,
    per_page: int,
    sort: str,
    order: str,
) -> dict[str, Any]:
    """Orders list as JSON."""
    period_key = _normalize_period(period)
    cache_key = (
        f"orders:{period_key}:{status or ''}:{page}:{per_page}:{sort}:{order}"
        if cache
        else None
    )

    async def _fetch():
        return await dashboard_service.list_orders(
            period=period_key,
            status_filter=status,
            page=page,
            per_page=per_page,
            sort=sort,
            order=order,
        )

    return await _get_cached_or_fetch(cache, cache_key, list_ttl, _fetch)


async def _render_search_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    list_ttl: int,
    q: str,
):
    """Search users HTML page."""
    if not await auth.authenticate(request):
        return RedirectResponse(url="/admin/login")
    cache_key = f"search:{q or ''}:50" if cache else None

    async def _fetch():
        return await dashboard_service.search_users(q, limit=50)

    if cache and cache_key:
        raw = await cache.get(cache_key)
        if raw is not None:
            data = cast(
                dict[str, Any],
                deserialize_admin_payload(raw),
            )
            users = data.get("users", [])
        else:
            users = await _fetch()
            await cache.set(
                cache_key,
                serialize_admin_payload({"query": q, "users": users}),
                list_ttl,
            )
    else:
        users = await _fetch()
    return templates.TemplateResponse(
        request,
        "search.html",
        {"query": q, "users": users},
    )


async def _api_search_json(
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    list_ttl: int,
    q: str,
) -> dict[str, Any]:
    """Search results as JSON."""
    cache_key = f"search:{q or ''}:20" if cache else None
    if cache and cache_key:
        raw = await cache.get(cache_key)
        if raw is not None:
            return cast(
                dict[str, Any],
                deserialize_admin_payload(raw),
            )
    users = await dashboard_service.search_users(q, limit=20)
    result = {"query": q, "users": users}
    if cache and cache_key:
        await cache.set(
            cache_key,
            serialize_admin_payload(result),
            list_ttl,
        )
    return result


def _make_require_admin(auth: AdminAuth):
    """Dependency: raise 401 if not authenticated."""

    async def _require_admin(request: Request) -> None:
        if not await auth.authenticate(request):
            raise HTTPException(status_code=401, detail="Не авторизован")

    return _require_admin


def _register_dashboard_html_routes(
    app: FastAPI,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    list_cache_ttl: int,
) -> None:
    """Register dashboard/referrers/list/detail/search HTML routes."""

    @app.get("/admin/dashboard", response_class=HTMLResponse)
    async def admin_dashboard(
        request: Request,
        period: str = "today",
        referrers_page: int = 1,
        referrers_per_page: int = 25,
        referrers_sort: str = "",
        referrers_order: str = "desc",
        referrers_filter: str = "all",
        timings: str = "",
    ):
        return await _render_dashboard_page(
            request,
            auth,
            dashboard_service,
            templates,
            cache,
            period,
            referrers_page,
            referrers_per_page,
            referrers_sort,
            referrers_order,
            referrers_filter,
            timings,
        )

    @app.get("/admin/referrers", response_class=HTMLResponse)
    async def admin_referrers(
        request: Request,
        period: str = "today",
        referrers_page: int = 1,
        referrers_per_page: int = 25,
        referrers_sort: str = "",
        referrers_order: str = "desc",
        referrers_filter: str = "all",
        timings: str = "",
    ):
        return await _render_referrers_page(
            request,
            auth,
            dashboard_service,
            templates,
            cache,
            period,
            referrers_page,
            referrers_per_page,
            referrers_sort,
            referrers_order,
            referrers_filter,
            timings,
        )

    @app.get("/admin/users/creators", response_class=HTMLResponse)
    async def admin_creators(
        request: Request,
        period: str = "today",
        only_new: bool = False,
        with_complaints: bool = False,
        page: int = 1,
        per_page: int = 25,
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
    ):
        return await _render_creators_page(
            request,
            auth,
            dashboard_service,
            templates,
            cache,
            list_cache_ttl,
            period,
            only_new,
            with_complaints,
            page,
            per_page,
            q,
            sort,
            order,
        )

    @app.get("/admin/users/advertisers", response_class=HTMLResponse)
    async def admin_advertisers(
        request: Request,
        page: int = 1,
        per_page: int = 25,
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
    ):
        return await _render_advertisers_page(
            request,
            auth,
            dashboard_service,
            templates,
            cache,
            list_cache_ttl,
            page,
            per_page,
            q,
            sort,
            order,
        )

    @app.get("/admin/orders", response_class=HTMLResponse)
    async def admin_orders(
        request: Request,
        period: str = "today",
        status: str | None = None,
        page: int = 1,
        per_page: int = 25,
        sort: str = "created_at",
        order: str = "desc",
        search: str | None = None,
    ):
        return await _render_orders_page(
            request,
            auth,
            dashboard_service,
            templates,
            cache,
            list_cache_ttl,
            period,
            status,
            page,
            per_page,
            sort,
            order,
            search,
        )

    @app.get("/admin/orders/{order_id}", response_class=HTMLResponse)
    async def admin_order_detail(request: Request, order_id: UUID):
        return await _render_order_detail_page(
            request,
            auth,
            dashboard_service,
            templates,
            order_id,
        )

    @app.get("/admin/users/{user_id}", response_class=HTMLResponse)
    async def admin_user_card(request: Request, user_id: UUID):
        return await _render_user_card_page(
            request,
            auth,
            dashboard_service,
            templates,
            user_id,
        )

    @app.get("/admin/search", response_class=HTMLResponse)
    async def admin_search(request: Request, q: str = ""):
        return await _render_search_page(
            request,
            auth,
            dashboard_service,
            templates,
            cache,
            list_cache_ttl,
            q,
        )


_FLOWCHART_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "product_flowchart.html"
)


def _register_flowchart_route(app: FastAPI, auth: AdminAuth) -> None:
    @app.get("/admin/flowchart", response_class=HTMLResponse)
    async def admin_flowchart(request: Request):
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        if not _FLOWCHART_PATH.exists():
            raise HTTPException(
                status_code=404,
                detail=(
                    "Flowchart not found. Run:"
                    " python scripts/generate_product_flowchart.py"
                ),
            )
        return HTMLResponse(content=_FLOWCHART_PATH.read_text())


def _register_dashboard_api_routes(
    app: FastAPI,
    require_admin,
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    list_cache_ttl: int,
) -> None:
    """Register dashboard/list/order/search API JSON routes."""

    @app.get("/admin/api/dashboard", dependencies=[Depends(require_admin)])
    async def dashboard_api(period: str = "today", timings: str = "") -> dict:
        return await _api_dashboard_json(
            dashboard_service, cache, period, timings
        )

    @app.get(
        "/admin/api/dashboard/charts", dependencies=[Depends(require_admin)]
    )
    async def dashboard_charts_api(period: str = "7d") -> dict:
        return await _api_charts_json(dashboard_service, cache, period)

    @app.get("/admin/api/users/creators", dependencies=[Depends(require_admin)])
    async def creators_api(
        period: str = "today",
        only_new: bool = False,
        with_complaints: bool = False,
        page: int = 1,
        per_page: int = 25,
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
    ) -> dict:
        return await _api_creators_json(
            dashboard_service,
            cache,
            list_cache_ttl,
            period,
            only_new,
            with_complaints,
            page,
            per_page,
            q,
            sort,
            order,
        )

    @app.get(
        "/admin/api/users/advertisers", dependencies=[Depends(require_admin)]
    )
    async def advertisers_api(
        page: int = 1,
        per_page: int = 25,
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
    ) -> dict:
        return await _api_advertisers_json(
            dashboard_service,
            cache,
            list_cache_ttl,
            page,
            per_page,
            q,
            sort,
            order,
        )

    @app.get("/admin/api/orders", dependencies=[Depends(require_admin)])
    async def orders_api(
        period: str = "today",
        status: str | None = None,
        page: int = 1,
        per_page: int = 25,
        sort: str = "created_at",
        order: str = "desc",
    ) -> dict:
        return await _api_orders_json(
            dashboard_service,
            cache,
            list_cache_ttl,
            period,
            status,
            page,
            per_page,
            sort,
            order,
        )

    @app.get(
        "/admin/api/orders/{order_id}", dependencies=[Depends(require_admin)]
    )
    async def order_api(order_id: UUID) -> dict:
        order = await dashboard_service.get_order_card(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Заказ не найден")
        return order

    @app.get("/admin/api/search", dependencies=[Depends(require_admin)])
    async def search_api(q: str = "") -> dict:
        return await _api_search_json(
            dashboard_service, cache, list_cache_ttl, q
        )


def _register_dashboard_routes(
    app: FastAPI,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None = None,
) -> None:
    """Register dashboard and list routes on the admin app."""
    _LIST_CACHE_TTL = 90
    require_admin = _make_require_admin(auth)
    _register_dashboard_html_routes(
        app, auth, dashboard_service, templates, cache, _LIST_CACHE_TTL
    )
    _register_flowchart_route(app, auth)
    _register_dashboard_api_routes(
        app, require_admin, dashboard_service, cache, _LIST_CACHE_TTL
    )


async def _get_obj_by_pk(
    view: ModelView,
    model_cls: type[T],
    pk: UUID,
) -> T | None:
    """Get model by pk, supporting both sync and async session makers."""
    if view.is_async:
        async with view.session_maker(expire_on_commit=False) as session:
            return await session.get(model_cls, pk)
    else:

        def _sync_get() -> T | None:
            with view.session_maker(expire_on_commit=False) as session:
                return session.get(model_cls, pk)

        return await asyncio.to_thread(_sync_get)


class UserAdmin(ModelView, model=UserModel):
    """Admin view for users."""

    can_delete = False
    name = "Пользователь"
    name_plural = "Пользователи"
    column_list = [
        UserModel.user_id,
        UserModel.telegram_id,
        UserModel.max_id,
        UserModel.messenger_type,
        UserModel.username,
        UserModel.telegram,
        UserModel.referral_code,
        UserModel.referral_payout_rate,
        UserModel.status,
        UserModel.admin,
        UserModel.issue_count,
        UserModel.created_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (UserModel.created_at, True)
    column_labels = {
        UserModel.user_id: "ID пользователя",
        UserModel.telegram_id: "Telegram ID",
        UserModel.max_id: "Max ID",
        UserModel.messenger_type: "Мессенджер",
        UserModel.username: "Имя пользователя",
        UserModel.telegram: "Telegram",
        UserModel.referral_code: "Реферальный код",
        UserModel.referral_payout_rate: "Процент выплаты рефералам",
        UserModel.status: "Статус",
        UserModel.admin: "Администратор",
        UserModel.issue_count: "Кол-во проблем",
        UserModel.created_at: "Дата создания",
    }
    form_columns = [
        UserModel.admin,
        UserModel.referral_payout_rate,
    ]

    async def update_model(self, request: Request, pk: str, data: dict):
        """Update user model with status change handling."""

        pk_uuid = UUID(pk)
        obj = await _get_obj_by_pk(self, UserModel, pk_uuid)
        old_status = obj.status if obj else None

        result = await super().update_model(request, pk, data)

        obj = await _get_obj_by_pk(self, UserModel, pk_uuid)
        new_status = obj.status if obj else None

        # If status changed to BLOCKED, log it
        if old_status != new_status and new_status == UserStatus.BLOCKED:
            try:
                container = _get_admin_container()
                if container:
                    user_role_service, _, _ = _get_services(container)
                    user = await user_role_service.get_user_by_id(UUID(pk))
                    if user:
                        logger.warning(
                            "User blocked via admin",
                            extra={
                                "user_id": str(user.user_id),
                                "telegram_id": user.telegram_id,
                                "max_id": user.max_id,
                                "username": user.username,
                                "previous_status": old_status.value
                                if old_status
                                else None,
                                "event_type": "user.blocked.admin",
                            },
                        )
            except Exception:
                logger.exception(
                    "Failed to log user blocked via admin",
                    extra={"pk": pk},
                )

        return result

    def list_query(self, request: Request):
        stmt = super().list_query(request)
        return stmt.where(UserModel.status != UserStatus.DELETED)

    def count_query(self, request: Request):
        stmt = super().count_query(request)
        return stmt.where(UserModel.status != UserStatus.DELETED)

    def form_edit_query(self, request: Request):
        stmt = super().form_edit_query(request)
        return stmt.where(UserModel.status != UserStatus.DELETED)


class BloggerProfileAdmin(ModelView, model=BloggerProfileModel):
    """Admin view for blogger profiles."""

    can_delete = False
    name = "Профиль креатора"
    name_plural = "Профили креаторов"
    column_list = [
        BloggerProfileModel.user_id,
        BloggerProfileModel.instagram_url,
        BloggerProfileModel.confirmed,
        BloggerProfileModel.city,
        BloggerProfileModel.phone,
        BloggerProfileModel.country,
        BloggerProfileModel.blogger_gender,
        BloggerProfileModel.audience_gender,
        BloggerProfileModel.audience_age_min,
        BloggerProfileModel.audience_age_max,
        BloggerProfileModel.audience_geo,
        BloggerProfileModel.price,
        BloggerProfileModel.barter,
        BloggerProfileModel.work_format,
        BloggerProfileModel.updated_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (BloggerProfileModel.updated_at, True)
    column_labels = {
        BloggerProfileModel.user_id: "ID пользователя",
        BloggerProfileModel.instagram_url: "Instagram",
        BloggerProfileModel.confirmed: "Подтверждён",
        BloggerProfileModel.city: "Город",
        BloggerProfileModel.phone: "Телефон",
        BloggerProfileModel.country: "Страна",
        BloggerProfileModel.blogger_gender: "Пол",
        BloggerProfileModel.audience_gender: "Пол аудитории",
        BloggerProfileModel.audience_age_min: "Возраст мин.",
        BloggerProfileModel.audience_age_max: "Возраст макс.",
        BloggerProfileModel.audience_geo: "Гео аудитории",
        BloggerProfileModel.price: "Цена",
        BloggerProfileModel.barter: "Бартер",
        BloggerProfileModel.work_format: "Формат работы",
        BloggerProfileModel.updated_at: "Обновлён",
    }

    async def update_model(self, request: Request, pk: str, data: dict) -> Any:
        """After save, refresh location from Nominatim if city changed."""
        result = await super().update_model(request, pk, data)
        if "city" in data:
            await _update_blogger_profile_location_from_nominatim(
                UUID(pk), data.get("city")
            )
        return result


class AdvertiserProfileAdmin(ModelView, model=AdvertiserProfileModel):
    """Admin view for advertiser profiles."""

    can_delete = False
    name = "Профиль заказчика"
    name_plural = "Профили заказчиков"
    column_list = [
        AdvertiserProfileModel.user_id,
        AdvertiserProfileModel.contact,
        AdvertiserProfileModel.brand,
        AdvertiserProfileModel.city,
        AdvertiserProfileModel.company_activity,
        AdvertiserProfileModel.site_link,
    ]
    column_sortable_list = list(column_list)
    column_labels = {
        AdvertiserProfileModel.user_id: "ID пользователя",
        AdvertiserProfileModel.contact: "Контакт",
        AdvertiserProfileModel.brand: "Бренд",
        AdvertiserProfileModel.city: "Город",
        AdvertiserProfileModel.company_activity: "Деятельность компании",
        AdvertiserProfileModel.site_link: "Сайт",
    }


def _truncate_50(value: str | None) -> str:
    """Truncate string to 50 chars with ellipsis if longer."""
    s = value or ""
    return s[:50] + ("…" if len(s) > 50 else "")


async def _handle_order_photo_upload(
    request: Request, auth: AdminAuth, config: AppConfig
) -> JSONResponse:
    """Validate an image and ask Telegram for a reusable photo file_id."""
    if not await auth.authenticate(request):
        return JSONResponse(
            {"error": "Требуется вход в админку"}, status_code=401
        )
    form = await request.form()
    upload = form.get("photo")
    if not isinstance(upload, StarletteUploadFile):
        return JSONResponse({"error": "Выберите PNG или JPG"}, status_code=400)
    content_type = (upload.content_type or "").lower()
    if content_type not in {"image/png", "image/jpeg"}:
        return JSONResponse(
            {"error": "Допустимы только PNG и JPG"}, status_code=400
        )
    image = await upload.read(10 * 1024 * 1024 + 1)
    if len(image) > 10 * 1024 * 1024:
        return JSONResponse(
            {"error": "Максимальный размер — 10 МБ"}, status_code=400
        )
    if not image.startswith(b"\x89PNG\r\n\x1a\n") and not image.startswith(
        b"\xff\xd8\xff"
    ):
        return JSONResponse(
            {"error": "Файл не похож на PNG или JPG"}, status_code=400
        )

    bot = Bot(token=config.bot.bot_token)
    try:
        sent = await bot.send_photo(
            chat_id=int(config.market.support_chat_id),
            photo=BufferedInputFile(
                image, filename=upload.filename or "order-image"
            ),
            caption="Изображение для шаблона заказа (сообщение будет удалено)",
        )
        photo_sizes = sent.photo
        try:
            await bot.delete_message(
                chat_id=sent.chat.id, message_id=sent.message_id
            )
        except Exception:
            logger.warning(
                "Could not remove temporary order photo from support chat"
            )
        if not photo_sizes:
            logger.error(
                "Telegram returned no photo sizes for uploaded order photo"
            )
            return JSONResponse(
                {"error": "Telegram не вернул данные фотографии"},
                status_code=502,
            )
        file_id = photo_sizes[-1].file_id
        return JSONResponse({"file_id": file_id})
    except Exception:
        logger.exception("Failed to upload order photo to Telegram")
        return JSONResponse(
            {
                "error": (
                    "Telegram не принял фото. Проверьте права бота "
                    "в чате поддержки."
                )
            },
            status_code=502,
        )
    finally:
        await bot.session.close()


def _order_duplicate_insert_data(source: OrderModel) -> dict[str, Any]:
    """Build insert payload: copy brief and filters, reset lifecycle fields."""
    skip = frozenset(
        {"order_id", "created_at", "updated_at", "completed_at"},
    )
    mapper = sa_inspect(OrderModel)
    data: dict[str, Any] = {}
    for col in mapper.columns:
        key = col.key
        if key in skip:
            continue
        if key == "status":
            data[key] = OrderStatus.NEW
        elif key == "last_round_robin_index":
            data[key] = 0
        else:
            data[key] = getattr(source, key)
    return data


class OrderAdmin(ModelView, model=OrderModel):
    """Admin view for orders with moderation support."""

    can_delete = False
    name = "Заказ"
    name_plural = "Заказы"
    list_template = "order_list.html"
    page_size = 25
    page_size_options = [25, 50, 100]
    column_list = [
        OrderModel.order_id,
        OrderModel.advertiser_id,
        OrderModel.order_type,
        OrderModel.offer_text,
        OrderModel.price,
        OrderModel.min_rating,
        OrderModel.bloggers_needed,
        OrderModel.status,
        OrderModel.geography,
        OrderModel.brief_link,
        OrderModel.created_at,
        OrderModel.completed_at,
    ]
    column_searchable_list = [
        OrderModel.offer_text,
        OrderModel.barter_description,
        OrderModel.product_link,
        OrderModel.geography,
        OrderModel.brief_link,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (OrderModel.created_at, True)
    column_formatters = {
        OrderModel.offer_text: lambda m, _: _truncate_50(  # type: ignore[attr-defined]
            getattr(m, "offer_text", None)
        ),
        OrderModel.barter_description: lambda m, _: _truncate_50(  # type: ignore[attr-defined]
            getattr(m, "barter_description", None)
        ),
    }
    column_labels = {
        OrderModel.order_id: "ID заказа",
        OrderModel.advertiser_id: "ID заказчика",
        OrderModel.product_link: "Ссылка на товар",
        OrderModel.offer_text: "Текст оффера",
        OrderModel.price: "Цена",
        OrderModel.bloggers_needed: "Нужно креаторов",
        OrderModel.content_usage: "Использование контента",
        OrderModel.deadlines: "Сроки",
        OrderModel.geography: "География",
        OrderModel.min_followers: "Мин. подписчиков",
        OrderModel.max_followers: "Макс. подписчиков",
        OrderModel.min_age: "Мин. возраст",
        OrderModel.max_age: "Макс. возраст",
        OrderModel.min_publications: "Мин. публикаций",
        OrderModel.max_publications: "Макс. публикаций",
        OrderModel.min_rating: "Мин. рейтинг",
        OrderModel.required_blogger_gender: "Пол",
        OrderModel.status: "Статус",
        OrderModel.created_at: "Дата создания",
        OrderModel.updated_at: "Дата обновления",
        OrderModel.completed_at: "Дата завершения",
        OrderModel.order_type: "Тип заказа",
        OrderModel.barter_description: "Описание бартера",
        OrderModel.product_photo_file_id: "ID фото товара",
        OrderModel.filter_by_price: "Фильтр по цене",
        OrderModel.price_filter_delta: "Дельта цены (диапазон ±)",
        OrderModel.filter_by_placement: "Фильтр по размещению",
        OrderModel.filter_by_barter: "Фильтр по бартеру",
        OrderModel.brief_link: "Ссылка на ТЗ",
    }
    form_columns = [
        OrderModel.order_type,
        OrderModel.product_link,
        OrderModel.offer_text,
        OrderModel.barter_description,
        OrderModel.price,
        OrderModel.bloggers_needed,
        OrderModel.status,
        OrderModel.content_usage,
        OrderModel.deadlines,
        OrderModel.geography,
        OrderModel.min_followers,
        OrderModel.max_followers,
        OrderModel.min_age,
        OrderModel.max_age,
        OrderModel.min_publications,
        OrderModel.max_publications,
        OrderModel.min_rating,
        OrderModel.required_blogger_gender,
        OrderModel.product_photo_file_id,
        OrderModel.filter_by_price,
        OrderModel.price_filter_delta,
        OrderModel.filter_by_placement,
        OrderModel.filter_by_barter,
        OrderModel.brief_link,
    ]
    edit_template = "order_edit.html"

    async def update_model(self, request: Request, pk: str, data: dict):
        """Update order with banned content check and activation publishing."""
        pk_uuid = UUID(pk)
        form_data = await request.form()
        managers_raw = str(form_data.get("managers", "") or "")

        obj = await _get_obj_by_pk(self, OrderModel, pk_uuid)
        old_status = obj.status if obj else None
        new_status_raw = data.get("status")
        new_status_active = (
            new_status_raw == "active" or new_status_raw == OrderStatus.ACTIVE
        )

        if new_status_active and old_status == OrderStatus.PENDING_MODERATION:
            container = _get_admin_container()
            if container:
                content_moderation, _, _ = _get_order_moderation_deps(container)
                if content_moderation.order_contains_banned_content(
                    product_link=data.get("product_link"),
                    offer_text=data.get("offer_text"),
                    barter_description=data.get("barter_description"),
                    content_usage=data.get("content_usage"),
                    geography=data.get("geography"),
                ):
                    matches = content_moderation.get_order_banned_matches(
                        product_link=data.get("product_link"),
                        offer_text=data.get("offer_text"),
                        barter_description=data.get("barter_description"),
                        content_usage=data.get("content_usage"),
                        geography=data.get("geography"),
                    )
                    raise ValueError(
                        f"Запрещённый контент. Найдено: {', '.join(matches)}. "
                        "Отредактируйте заявку."
                    )

        result = await super().update_model(request, pk, data)

        if "geography" in data:
            await _update_order_location_geometry_after_geography_change(
                pk_uuid, data.get("geography")
            )

        obj = await _get_obj_by_pk(self, OrderModel, pk_uuid)
        new_status = obj.status if obj else None

        if (
            old_status != OrderStatus.ACTIVE
            and new_status == OrderStatus.ACTIVE
        ):
            await _publish_order_activation(pk_uuid)

        try:
            await _update_order_managers(pk_uuid, managers_raw)
        except Exception:
            logger.exception(
                "Failed to update order managers",
                extra={"order_id": str(pk_uuid)},
            )

        return result

    def list_query(self, request: Request):
        stmt = super().list_query(request)
        return stmt.where(OrderModel.status != OrderStatus.DELETED)

    def count_query(self, request: Request):
        stmt = super().count_query(request)
        return stmt.where(OrderModel.status != OrderStatus.DELETED)

    def form_edit_query(self, request: Request):
        stmt = super().form_edit_query(request)
        return stmt.where(OrderModel.status != OrderStatus.DELETED)

    @action(
        name="duplicate_order",
        label="Дублировать заказ",
        add_in_list=True,
        add_in_detail=True,
    )
    async def duplicate_order_action(
        self, request: Request
    ) -> RedirectResponse:
        """Insert a copy of the selected order and redirect to its edit page."""
        raw = (request.query_params.get("pks") or "").strip()
        pks = [p.strip() for p in raw.split(",") if p.strip()]
        if len(pks) != 1:
            raise HTTPException(
                status_code=400,
                detail="Выберите ровно один заказ для дублирования.",
            )
        try:
            pk_uuid = UUID(pks[0])
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Некорректный идентификатор заказа.",
            ) from exc

        source = await _get_obj_by_pk(self, OrderModel, pk_uuid)
        if source is None or source.status == OrderStatus.DELETED:
            raise HTTPException(status_code=404, detail="Заказ не найден.")

        created = await self.insert_model(
            request, _order_duplicate_insert_data(source)
        )
        return RedirectResponse(
            str(
                request.url_for(
                    "admin:edit",
                    identity=self.identity,
                    pk=str(created.order_id),
                )
            ),
            status_code=302,
        )


class OfferDispatchAdmin(ModelView, model=OfferDispatchModel):
    """Admin view for offer dispatches and responses."""

    can_delete = False
    name = "Оффер (отправка/отклик)"
    name_plural = "Офферы (отправки и отклики)"
    column_list = [
        OfferDispatchModel.order_id,
        OfferDispatchModel.blogger_id,
        OfferDispatchModel.created_at,
        OfferDispatchModel.updated_at,
        OfferDispatchModel.accepted,
        OfferDispatchModel.in_offer,
        OfferDispatchModel.rejection_reason,
        OfferDispatchModel.desired_price,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (OfferDispatchModel.created_at, True)
    column_searchable_list = [OfferDispatchModel.rejection_reason]
    column_labels = {
        OfferDispatchModel.order_id: "ID заказа",
        OfferDispatchModel.blogger_id: "ID креатора",
        OfferDispatchModel.created_at: "Отправлено",
        OfferDispatchModel.updated_at: "Обновлено",
        OfferDispatchModel.accepted: "Принял оффер",
        OfferDispatchModel.in_offer: "В заказе",
        OfferDispatchModel.rejection_reason: "Причина отказа",
        OfferDispatchModel.desired_price: "Желаемая цена",
    }


class BloggerRatingAdmin(ModelView, model=BloggerRatingModel):
    """Admin view for blogger ratings."""

    can_delete = False
    name = "Рейтинг креатора"
    name_plural = "Рейтинги креаторов"
    column_list = [
        BloggerRatingModel.rating_id,
        BloggerRatingModel.blogger_id,
        BloggerRatingModel.order_id,
        BloggerRatingModel.rater_id,
        BloggerRatingModel.rater_role,
        BloggerRatingModel.score,
        BloggerRatingModel.comment,
        BloggerRatingModel.created_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (BloggerRatingModel.created_at, True)
    column_searchable_list = [BloggerRatingModel.comment]
    form_columns = [
        BloggerRatingModel.blogger_id,
        BloggerRatingModel.order_id,
        BloggerRatingModel.rater_id,
        BloggerRatingModel.rater_role,
        BloggerRatingModel.score,
        BloggerRatingModel.comment,
    ]
    column_labels = {
        BloggerRatingModel.rating_id: "ID рейтинга",
        BloggerRatingModel.blogger_id: "ID креатора",
        BloggerRatingModel.order_id: "ID заказа",
        BloggerRatingModel.rater_id: "Кто оценил",
        BloggerRatingModel.rater_role: "Роль",
        BloggerRatingModel.score: "Оценка",
        BloggerRatingModel.comment: "Комментарий",
        BloggerRatingModel.created_at: "Создан",
    }


class InteractionAdmin(ModelView, model=InteractionModel):
    """Read-only interactions; use protected financial review commands."""

    can_create = False
    can_edit = False
    can_delete = False
    name = "Взаимодействие"
    name_plural = "Взаимодействия"
    column_list = [
        InteractionModel.interaction_id,
        InteractionModel.order_id,
        InteractionModel.blogger_id,
        InteractionModel.advertiser_id,
        InteractionModel.status,
        InteractionModel.from_advertiser,
        InteractionModel.from_blogger,
        InteractionModel.created_at,
        InteractionModel.updated_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (InteractionModel.created_at, True)
    column_labels = {
        InteractionModel.interaction_id: "ID взаимодействия",
        InteractionModel.order_id: "ID заказа",
        InteractionModel.blogger_id: "ID креатора",
        InteractionModel.advertiser_id: "ID заказчика",
        InteractionModel.status: "Статус",
        InteractionModel.from_advertiser: "От заказчика",
        InteractionModel.from_blogger: "От креатора",
        InteractionModel.created_at: "Создано",
        InteractionModel.updated_at: "Обновлено",
    }
    form_columns = [
        InteractionModel.status,
    ]

    async def update_model(self, request: Request, pk: str, data: dict):
        """Reject raw status edits; use audited financial review."""
        raise PermissionError("Use an audited financial case review command")

    def list_query(self, request: Request):
        stmt = super().list_query(request)
        return stmt.where(InteractionModel.status != InteractionStatus.DELETED)

    def count_query(self, request: Request):
        stmt = super().count_query(request)
        return stmt.where(InteractionModel.status != InteractionStatus.DELETED)

    def form_edit_query(self, request: Request):
        stmt = super().form_edit_query(request)
        return stmt.where(InteractionModel.status != InteractionStatus.DELETED)


class InstagramVerificationAdmin(
    ModelView, model=InstagramVerificationCodeModel
):
    """Admin view for Instagram verification codes."""

    can_delete = False
    name = "Код верификации Instagram"
    name_plural = "Коды верификации Instagram"
    column_list = [
        InstagramVerificationCodeModel.code_id,
        InstagramVerificationCodeModel.user_id,
        InstagramVerificationCodeModel.code,
        InstagramVerificationCodeModel.expires_at,
        InstagramVerificationCodeModel.used,
    ]
    column_sortable_list = list(column_list)
    column_labels = {
        InstagramVerificationCodeModel.code_id: "ID кода",
        InstagramVerificationCodeModel.user_id: "ID пользователя",
        InstagramVerificationCodeModel.code: "Код",
        InstagramVerificationCodeModel.expires_at: "Истекает",
        InstagramVerificationCodeModel.used: "Использован",
    }


class ComplaintAdmin(ModelView, model=ComplaintModel):
    """Admin view for complaints."""

    can_delete = False
    name = "Жалоба"
    name_plural = "Жалобы"
    column_list = [
        ComplaintModel.complaint_id,
        ComplaintModel.reporter_id,
        ComplaintModel.reported_id,
        ComplaintModel.order_id,
        ComplaintModel.reason,
        ComplaintModel.file_ids,
        ComplaintModel.status,
        ComplaintModel.created_at,
        ComplaintModel.reviewed_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (ComplaintModel.created_at, True)
    column_labels = {
        ComplaintModel.complaint_id: "ID жалобы",
        ComplaintModel.reporter_id: "ID заявителя",
        ComplaintModel.reported_id: "ID нарушителя",
        ComplaintModel.order_id: "ID заказа",
        ComplaintModel.reason: "Причина",
        ComplaintModel.file_ids: "ID файлов",
        ComplaintModel.status: "Статус",
        ComplaintModel.created_at: "Создана",
        ComplaintModel.reviewed_at: "Рассмотрена",
    }
    form_columns = [
        ComplaintModel.status,
    ]

    async def update_model(self, request: Request, pk: str, data: dict):
        """Update complaint model with automatic user blocking."""

        pk_uuid = UUID(pk)
        obj = await _get_obj_by_pk(self, ComplaintModel, pk_uuid)
        old_status = obj.status if obj else None
        reported_id = obj.reported_id if obj else None

        result = await super().update_model(request, pk, data)

        obj = await _get_obj_by_pk(self, ComplaintModel, pk_uuid)
        new_status = obj.status if obj else None

        # If status changed to ACTION_TAKEN, block the reported user
        if (
            old_status != new_status
            and new_status == ComplaintStatus.ACTION_TAKEN
            and reported_id
        ):
            try:
                container = _get_admin_container()
                if container:
                    user_role_service, complaint_service, _ = _get_services(
                        container
                    )
                    # Update complaint status via service (sets reviewed_at)
                    await complaint_service.resolve_complaint_with_action(
                        UUID(pk)
                    )
                    # Block the reported user
                    await user_role_service.update_status(
                        reported_id, UserStatus.BLOCKED
                    )
            except Exception:
                logger.exception(
                    "resolve complaint and block user failed (ACTION_TAKEN)",
                    extra={
                        "complaint_id": pk,
                        "reported_id": str(reported_id),
                    },
                )
        elif (
            old_status != new_status and new_status == ComplaintStatus.DISMISSED
        ):
            try:
                container = _get_admin_container()
                if container:
                    _, complaint_service, _ = _get_services(container)
                    # Update complaint status via service (sets reviewed_at)
                    await complaint_service.dismiss_complaint(UUID(pk))
            except Exception:
                logger.exception(
                    "Failed to run dismiss_complaint after admin set DISMISSED",
                    extra={"complaint_id": pk},
                )

        return result

    def list_query(self, request: Request):
        stmt = super().list_query(request)
        return stmt.where(ComplaintModel.status != ComplaintStatus.DELETED)

    def count_query(self, request: Request):
        stmt = super().count_query(request)
        return stmt.where(ComplaintModel.status != ComplaintStatus.DELETED)

    def form_edit_query(self, request: Request):
        stmt = super().form_edit_query(request)
        return stmt.where(ComplaintModel.status != ComplaintStatus.DELETED)


class CountryAdmin(ModelView, model=CountryModel):
    """Admin view for countries."""

    name = "Страна"
    name_plural = "Страны"
    icon = "fa-solid fa-globe"
    form_include_pk = True
    column_list = [
        CountryModel.code,
        CountryModel.name_native,
        CountryModel.currency_code,
        CountryModel.currency_symbol,
        CountryModel.tax_rate,
        CountryModel.enabled,
    ]
    column_sortable_list = list(column_list)
    column_labels = {
        CountryModel.code: "Код",
        CountryModel.name_native: "Название",
        CountryModel.currency_code: "Валюта",
        CountryModel.currency_symbol: "Символ валюты",
        CountryModel.tax_rate: "Ставка налога",
        CountryModel.enabled: "Активна",
    }
    form_columns = [
        CountryModel.code,
        CountryModel.name_native,
        CountryModel.currency_code,
        CountryModel.currency_symbol,
        CountryModel.tax_rate,
        CountryModel.enabled,
    ]


class ContactPricingAdmin(ModelView, model=ContactPricingModel):
    """Admin view for contact pricing."""

    can_delete = False
    form_include_pk = True
    name = "Цена контакта"
    name_plural = "Цены контактов"
    column_list = [
        ContactPricingModel.country_code,
        ContactPricingModel.bloggers_count,
        ContactPricingModel.price,
        ContactPricingModel.currency,
        ContactPricingModel.updated_at,
    ]
    column_sortable_list = list(column_list)
    column_labels = {
        ContactPricingModel.country_code: "Страна",
        ContactPricingModel.bloggers_count: "Кол-во креаторов",
        ContactPricingModel.price: "Цена",
        ContactPricingModel.currency: "Валюта",
        ContactPricingModel.updated_at: "Обновлено",
    }
    form_columns = [
        ContactPricingModel.country_code,
        ContactPricingModel.bloggers_count,
        ContactPricingModel.price,
        ContactPricingModel.currency,
    ]


class LanguageAdmin(ModelView, model=LanguageModel):
    """Admin view for languages."""

    name = "Язык"
    name_plural = "Языки"
    icon = "fa-solid fa-language"
    form_include_pk = True
    column_list = [
        LanguageModel.code,
        LanguageModel.name_native,
        LanguageModel.enabled,
    ]
    column_labels = {
        LanguageModel.code: "Код",
        LanguageModel.name_native: "Название",
        LanguageModel.enabled: "Активен",
    }
    form_columns = [
        LanguageModel.code,
        LanguageModel.name_native,
        LanguageModel.enabled,
    ]


class BotTextAdmin(ModelView, model=BotTextModel):
    """Admin view for localized bot texts (key, locale, value)."""

    can_delete = False
    name = "Текст бота"
    name_plural = "Тексты бота"
    column_list = [
        BotTextModel.key,
        BotTextModel.locale,
        BotTextModel.value,
        BotTextModel.updated_at,
    ]
    column_sortable_list = [BotTextModel.key, BotTextModel.locale]
    column_labels = {
        BotTextModel.key: "Ключ",
        BotTextModel.locale: "Локаль",
        BotTextModel.value: "Текст",
        BotTextModel.updated_at: "Обновлено",
    }
    form_columns = [
        BotTextModel.key,
        BotTextModel.locale,
        BotTextModel.value,
    ]


class NpsResponseAdmin(ModelView, model=NpsResponseModel):
    """Admin view for NPS responses (read-only)."""

    name = "NPS ответ"
    name_plural = "NPS ответы"
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [
        NpsResponseModel.id,
        NpsResponseModel.user_id,
        NpsResponseModel.score,
        NpsResponseModel.comment,
        NpsResponseModel.created_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (NpsResponseModel.created_at, True)
    column_labels = {
        NpsResponseModel.id: "ID",
        NpsResponseModel.user_id: "ID пользователя",
        NpsResponseModel.score: "Оценка",
        NpsResponseModel.comment: "Комментарий",
        NpsResponseModel.created_at: "Дата",
    }


class PayoutRequestAdmin(ModelView, model=PayoutRequestModel):
    """Read-only legacy payout requests.

    Creation and mark-paid use guarded commands, never generic recipient,
    amount or status forms. Disputed wallets require audited financial review.
    """

    name = "Заявка на вывод"
    name_plural = "Заявки на вывод"
    can_create = False
    # Generic amount/recipient/status editing bypasses the payout safety-stop.
    can_edit = False
    can_delete = False
    column_list = [
        PayoutRequestModel.request_id,
        PayoutRequestModel.user_id,
        PayoutRequestModel.requested_at,
        PayoutRequestModel.status,
        PayoutRequestModel.amount,
        PayoutRequestModel.currency,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (PayoutRequestModel.requested_at, True)
    form_columns = [
        PayoutRequestModel.status,
        PayoutRequestModel.amount,
    ]
    column_labels = {
        PayoutRequestModel.request_id: "ID заявки",
        PayoutRequestModel.user_id: "ID пользователя",
        PayoutRequestModel.requested_at: "Дата запроса",
        PayoutRequestModel.status: "Статус",
        PayoutRequestModel.amount: "Сумма",
        PayoutRequestModel.currency: "Валюта",
    }

    def list_query(self, request: Request):
        stmt = super().list_query(request)
        return stmt.where(
            PayoutRequestModel.status != PayoutRequestStatus.DELETED
        )

    def count_query(self, request: Request):
        stmt = super().count_query(request)
        return stmt.where(
            PayoutRequestModel.status != PayoutRequestStatus.DELETED
        )

    def form_edit_query(self, request: Request):
        stmt = super().form_edit_query(request)
        return stmt.where(
            PayoutRequestModel.status != PayoutRequestStatus.DELETED
        )


class ReferralIncomeEntryAdmin(ModelView, model=ReferralIncomeEntryModel):
    """Read-only admin view for referral income entries."""

    name = "Реферальное начисление"
    name_plural = "Реферальные начисления"
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [
        ReferralIncomeEntryModel.entry_id,
        ReferralIncomeEntryModel.referrer_user_id,
        ReferralIncomeEntryModel.referred_user_id,
        ReferralIncomeEntryModel.order_id,
        ReferralIncomeEntryModel.income_type,
        ReferralIncomeEntryModel.currency,
        ReferralIncomeEntryModel.platform_revenue,
        ReferralIncomeEntryModel.commission_rate,
        ReferralIncomeEntryModel.commission_amount,
        ReferralIncomeEntryModel.created_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (ReferralIncomeEntryModel.created_at, True)
    column_labels = {
        ReferralIncomeEntryModel.entry_id: "ID",
        ReferralIncomeEntryModel.referrer_user_id: "Реферальщик",
        ReferralIncomeEntryModel.referred_user_id: "Реферал",
        ReferralIncomeEntryModel.order_id: "Заказ",
        ReferralIncomeEntryModel.income_type: "Тип",
        ReferralIncomeEntryModel.currency: "Валюта",
        ReferralIncomeEntryModel.platform_revenue: "Доход платформы",
        ReferralIncomeEntryModel.commission_rate: "Ставка",
        ReferralIncomeEntryModel.commission_amount: "Комиссия",
        ReferralIncomeEntryModel.created_at: "Дата",
    }


class PaymentAdmin(ModelView, model=PaymentModel):
    """Admin view for payments."""

    name = "Платёж"
    name_plural = "Платежи"
    can_create = True
    can_edit = True
    can_delete = False
    column_list = [
        PaymentModel.payment_id,
        PaymentModel.order_id,
        PaymentModel.provider,
        PaymentModel.status,
        PaymentModel.amount,
        PaymentModel.currency,
        PaymentModel.external_id,
        PaymentModel.created_at,
        PaymentModel.paid_at,
    ]
    column_sortable_list = [
        PaymentModel.status,
        PaymentModel.amount,
        PaymentModel.created_at,
        PaymentModel.paid_at,
    ]
    column_default_sort = (PaymentModel.created_at, True)
    form_columns = [
        PaymentModel.order,
        PaymentModel.provider,
        PaymentModel.status,
        PaymentModel.amount,
        PaymentModel.currency,
        PaymentModel.external_id,
        PaymentModel.paid_at,
    ]
    column_labels = {
        PaymentModel.payment_id: "ID платежа",
        PaymentModel.order_id: "ID заказа",
        PaymentModel.order: "Заказ",
        PaymentModel.provider: "Провайдер",
        PaymentModel.status: "Статус",
        PaymentModel.amount: "Сумма",
        PaymentModel.currency: "Валюта",
        PaymentModel.external_id: "Внешний ID",
        PaymentModel.created_at: "Дата создания",
        PaymentModel.paid_at: "Дата оплаты",
    }
    form_overrides = {
        "provider": SelectField,
        "currency": SelectField,
    }
    form_args = {
        "provider": {
            "choices": [
                ("manual", "manual"),
                ("yookassa_telegram", "yookassa_telegram"),
                ("telegram_payments", "telegram_payments"),
            ],
        },
        "currency": {
            "choices": [
                ("RUB", "RUB"),
                ("USD", "USD"),
                ("EUR", "EUR"),
                ("KZT", "KZT"),
                ("UZS", "UZS"),
                ("BYN", "BYN"),
            ],
        },
    }


class AuditLogAdmin(ModelView, model=AuditLogModel):
    """Read-only audit log viewer."""

    name = "Аудит лог"
    name_plural = "Аудит логи"
    icon = "fa-solid fa-clock-rotate-left"
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [
        AuditLogModel.id,
        AuditLogModel.entity_type,
        AuditLogModel.entity_id,
        AuditLogModel.action,
        AuditLogModel.old_values,
        AuditLogModel.new_values,
        AuditLogModel.changed_by,
        AuditLogModel.changed_at,
    ]
    column_sortable_list = [
        AuditLogModel.entity_type,
        AuditLogModel.action,
        AuditLogModel.changed_at,
    ]
    column_default_sort = (AuditLogModel.changed_at, True)
    column_labels = {
        AuditLogModel.id: "ID",
        AuditLogModel.entity_type: "Тип сущности",
        AuditLogModel.entity_id: "ID сущности",
        AuditLogModel.action: "Действие",
        AuditLogModel.old_values: "Старые значения",
        AuditLogModel.new_values: "Новые значения",
        AuditLogModel.changed_by: "Кем изменено",
        AuditLogModel.changed_at: "Когда",
    }
    column_searchable_list = [AuditLogModel.entity_type]


class DashboardLinkView(BaseView):
    """Sidebar link: redirect to dashboard (no intermediate page)."""

    name = "Дашборд"
    icon = "fa-solid fa-chart-line"

    @expose("/dashboard-mvp", methods=["GET"])
    @login_required
    async def dashboard_redirect(self, request: Request):
        """Redirect to dashboard page."""
        return RedirectResponse(url="/admin/dashboard")


async def _inject_order_eligible_bloggers_count(
    context: dict[str, Any],
    model_view: Any,
    model: Any,
) -> None:
    """Set context['eligible_bloggers_count'] for OrderAdmin edit view."""
    if not isinstance(model_view, OrderAdmin):
        return
    try:
        container = _get_admin_container()
        if container and getattr(container, "session_factory", None):
            dispatch_svc = container.build_offer_dispatch_service()
            count = await dispatch_svc.count_eligible_bloggers(model.order_id)
            context["eligible_bloggers_count"] = count
        else:
            context["eligible_bloggers_count"] = None
    except Exception:
        context["eligible_bloggers_count"] = None


async def _inject_order_managers(
    context: dict[str, Any],
    model_view: Any,
    model: Any,
) -> None:
    """Pre-populate managers field with current manager usernames."""
    if not isinstance(model_view, OrderAdmin) or model is None:
        return
    try:
        container = _get_admin_container()
        if container:
            manager_service = container.build_manager_service()
            manager_order_repo = manager_service.manager_order_repo
            user_repo = manager_service.user_repo
            tm = container.transaction_manager
            usernames: list[str] = []
            if tm:
                async with tm.transaction() as session:
                    manager_orders = await manager_order_repo.list_by_order(
                        model.order_id, session=session
                    )
                    for mo in manager_orders:
                        user = await user_repo.get_by_id(
                            mo.user_id, session=session
                        )
                        if user and user.telegram:
                            usernames.append(f"@{user.telegram}")
            context["managers_value"] = ", ".join(usernames)
    except Exception:
        logger.exception("Failed to inject order managers")


class EnumAwareAdmin(Admin):
    """Admin that fixes enum select fields showing first option instead of DB.

    SQLAdmin's conv_enum uses SQLAlchemy Enum.enums which with values_callable
    returns string values (e.g. 'pending_moderation'). The form receives
    Python enum from model (OrderStatus.PENDING_MODERATION). SelectField
    compares these and finds no match, defaulting to first option. We pass
    enum.value in form data so the select shows the correct option.
    """

    def _edit_form_data(
        self, model: Any, model_view: ModelView
    ) -> dict[str, Any]:
        """Build form data for edit. Enum fields use .value for SelectField.

        WTForms gives obj precedence over data, so we pass only data (no obj)
        with enum values as strings to fix select display.
        """
        data = dict(self._normalize_wtform_data(model))
        for prop_name in model_view._form_prop_names:
            if prop_name in data:
                continue
            try:
                value = getattr(model, prop_name, None)
            except Exception:
                continue
            if value is not None and isinstance(value, Enum):
                data[prop_name] = value.value
            elif value is not None:
                data[prop_name] = value
        return data

    @login_required
    async def edit(self, request: Request):  # pragma: no cover
        """Override edit to pass enum .value for correct select display."""
        from starlette.exceptions import HTTPException
        from starlette.responses import RedirectResponse

        await self._edit(request)

        identity = request.path_params["identity"]
        model_view = self._find_model_view(identity)

        model = await model_view.get_object_for_edit(request)
        if not model:
            raise HTTPException(status_code=404)

        Form = await model_view.scaffold_form(model_view._form_edit_rules)
        form_data = self._edit_form_data(model, model_view)
        context = {
            "obj": model,
            "model_view": model_view,
            "form": Form(data=form_data),
        }
        await _inject_order_eligible_bloggers_count(context, model_view, model)
        await _inject_order_managers(context, model_view, model)

        if request.method == "GET":
            return await self.templates.TemplateResponse(
                request, model_view.edit_template, context
            )

        form_data_post = await self._handle_form_data(request, model)
        form = Form(form_data_post)
        if not form.validate():
            context["form"] = form
            return await self.templates.TemplateResponse(
                request, model_view.edit_template, context, status_code=400
            )

        form_data_dict = self._denormalize_wtform_data(form.data, model)
        try:
            if (
                model_view.save_as
                and form_data_post.get("save") == "Save as new"
            ):
                obj = await model_view.insert_model(request, form_data_dict)
            else:
                obj = await model_view.update_model(
                    request, pk=request.path_params["pk"], data=form_data_dict
                )
        except Exception as e:
            logger.exception(e)
            context["error"] = str(e)
            return await self.templates.TemplateResponse(
                request, model_view.edit_template, context, status_code=400
            )

        url = self.get_save_redirect_url(
            request=request,
            form=form_data_post,
            obj=obj,
            model_view=model_view,
        )
        return RedirectResponse(url=url, status_code=302)


def _add_health_route(app: FastAPI, engine) -> None:
    """Register /health endpoint that checks DB connectivity."""

    @app.get("/health")
    async def health() -> dict[str, bool | str]:
        db_ok = True
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "db": db_ok}


def _add_admin_views(admin: Admin) -> None:
    """Register all SQLAdmin model and base views."""
    admin.add_base_view(DashboardLinkView)
    admin.add_view(UserAdmin)
    admin.add_view(BloggerProfileAdmin)
    admin.add_view(AdvertiserProfileAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(BloggerRatingAdmin)
    admin.add_view(OfferDispatchAdmin)
    admin.add_view(InteractionAdmin)
    admin.add_view(InstagramVerificationAdmin)
    admin.add_view(ComplaintAdmin)
    admin.add_view(CountryAdmin)
    admin.add_view(ContactPricingAdmin)
    admin.add_view(LanguageAdmin)
    admin.add_view(BotTextAdmin)
    admin.add_view(NpsResponseAdmin)
    admin.add_view(PaymentAdmin)
    admin.add_view(PayoutRequestAdmin)
    admin.add_view(ReferralIncomeEntryAdmin)
    admin.add_view(AuditLogAdmin)


def create_admin_app() -> FastAPI:
    """Create a FastAPI app with SQLAdmin."""

    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )

    log_startup_info(logger=logger, service_name="admin", config=config)
    if not config.admin.admin_secret:
        raise ValueError("ADMIN_SECRET is required for SQLAdmin.")
    if not config.admin.admin_password:
        raise ValueError("ADMIN_PASSWORD is required for SQLAdmin.")

    container = Container(config)
    engine = container.get_admin_engine()
    app = FastAPI(title=config.admin.admin_site_name)
    app.add_middleware(SessionMiddleware, secret_key=config.admin.admin_secret)

    _add_health_route(app, engine)

    auth = AdminAuth(
        secret_key=config.admin.admin_secret,
        username=config.admin.admin_username,
        password=config.admin.admin_password,
    )
    dashboard_service = _build_dashboard_service(config, container)
    templates = _build_templates(app)
    admin_cache = AdminCache(
        redis_url=config.redis.redis_url,
        enabled=config.redis.use_redis_storage,
        max_connections=config.redis.redis_max_connections,
        socket_timeout=config.redis.redis_socket_timeout,
        socket_connect_timeout=config.redis.redis_socket_connect_timeout,
    )
    _register_dashboard_routes(
        app, auth, dashboard_service, templates, cache=admin_cache
    )

    @app.post("/admin/order-photo-upload")
    async def upload_order_photo(request: Request) -> JSONResponse:
        """Upload an order image and return its Telegram file_id."""
        return await _handle_order_photo_upload(request, auth, config)

    admin = EnumAwareAdmin(
        app,
        engine,
        authentication_backend=auth,
        base_url="/admin",
        templates_dir=str(Path(__file__).parent / "templates"),
    )

    global _admin_container
    _admin_container = container

    _add_admin_views(admin)

    @app.on_event("shutdown")
    async def _dispose_container() -> None:
        await container.dispose()

    return app


app = create_admin_app()
