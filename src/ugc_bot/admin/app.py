"""SQLAdmin application setup."""

import asyncio
import logging
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar, cast
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from sqladmin import Admin, ModelView
from sqladmin.authentication import login_required
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from ugc_bot.admin.auth import AdminAuth
from ugc_bot.admin.dashboard_service import (
    AdminDashboardService,
    DelayThresholds,
    PeriodKey,
)
from ugc_bot.application.ports import OrderRepository
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import AppConfig, load_config
from ugc_bot.container import Container
from ugc_bot.domain.enums import (
    ComplaintStatus,
    InteractionStatus,
    OrderStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ComplaintModel,
    ContactPricingModel,
    InstagramVerificationCodeModel,
    InteractionModel,
    ManagerModel,
    OrderModel,
    OrderResponseModel,
    UserModel,
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
    outbox_publisher, _ = container.build_outbox_deps()
    order_repo = container.build_repos()["order_repo"]
    return (content_moderation, outbox_publisher, order_repo)


T = TypeVar("T")
_DASHBOARD_PERIODS = ("today", "yesterday", "7d", "30d")
_STATUS_LABELS = {
    "active": "Активен",
    "completed": "Завершён",
    "archive": "Архив",
    "complaint": "Жалоба",
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
    return AdminDashboardService(
        session_factory=container.session_factory,
        timezone_name=config.admin.admin_dashboard_timezone,
        thresholds=thresholds,
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


def _register_dashboard_routes(  # noqa: C901
    app: FastAPI,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
) -> None:
    """Register dashboard and list routes on the admin app."""

    async def _require_admin(request: Request) -> None:
        """Raise HTTP 401 when admin session is missing."""
        if not await auth.authenticate(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/admin/dashboard", response_class=HTMLResponse)
    async def admin_dashboard(
        request: Request,
        period: str = "today",
    ):
        """Render dashboard page with KPI cards."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        period_key = _normalize_period(period)
        payload = await dashboard_service.get_dashboard(period_key)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "payload": payload,
                "period": period_key,
                "periods": _DASHBOARD_PERIODS,
                "status_labels": _STATUS_LABELS,
                "delay_reason_labels": _DELAY_REASON_LABELS,
            },
        )

    @app.get("/admin/users/creators", response_class=HTMLResponse)
    async def admin_creators(
        request: Request,
        period: str = "today",
        only_new: bool = False,
        with_complaints: bool = False,
    ):
        """Render creator list page."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        period_key = _normalize_period(period)
        creators = await dashboard_service.list_creators(
            period=period_key,
            only_new=only_new,
            only_with_complaints=with_complaints,
        )
        return templates.TemplateResponse(
            request,
            "creators.html",
            {
                "creators": creators,
                "period": period_key,
                "periods": _DASHBOARD_PERIODS,
                "only_new": only_new,
                "with_complaints": with_complaints,
            },
        )

    @app.get("/admin/users/advertisers", response_class=HTMLResponse)
    async def admin_advertisers(request: Request):
        """Render advertiser list page."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        advertisers = await dashboard_service.list_advertisers()
        return templates.TemplateResponse(
            request,
            "advertisers.html",
            {"advertisers": advertisers},
        )

    @app.get("/admin/orders", response_class=HTMLResponse)
    async def admin_orders(
        request: Request,
        period: str = "today",
        status: str | None = None,
    ):
        """Render order list page."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        period_key = _normalize_period(period)
        orders = await dashboard_service.list_orders(
            period=period_key, status_filter=status
        )
        return templates.TemplateResponse(
            request,
            "orders.html",
            {
                "orders": orders,
                "period": period_key,
                "periods": _DASHBOARD_PERIODS,
                "status_filter": status,
                "status_labels": _STATUS_LABELS,
            },
        )

    @app.get("/admin/orders/{order_id}", response_class=HTMLResponse)
    async def admin_order_detail(request: Request, order_id: UUID):
        """Render order detail page."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        order = await dashboard_service.get_order_card(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        return templates.TemplateResponse(
            request,
            "order_detail.html",
            {
                "order": order,
                "status_labels": _STATUS_LABELS,
            },
        )

    @app.get("/admin/api/dashboard", dependencies=[Depends(_require_admin)])
    async def dashboard_api(period: str = "today") -> dict:
        """Return dashboard data as JSON."""
        period_key = _normalize_period(period)
        return await dashboard_service.get_dashboard(period_key)

    @app.get(
        "/admin/api/users/creators", dependencies=[Depends(_require_admin)]
    )
    async def creators_api(
        period: str = "today",
        only_new: bool = False,
        with_complaints: bool = False,
    ) -> dict:
        """Return creator list as JSON."""
        period_key = _normalize_period(period)
        creators = await dashboard_service.list_creators(
            period=period_key,
            only_new=only_new,
            only_with_complaints=with_complaints,
        )
        return {"items": creators}

    @app.get(
        "/admin/api/users/advertisers", dependencies=[Depends(_require_admin)]
    )
    async def advertisers_api() -> dict:
        """Return advertiser list as JSON."""
        advertisers = await dashboard_service.list_advertisers()
        return {"items": advertisers}

    @app.get("/admin/api/orders", dependencies=[Depends(_require_admin)])
    async def orders_api(
        period: str = "today", status: str | None = None
    ) -> dict:
        """Return order list as JSON."""
        period_key = _normalize_period(period)
        orders = await dashboard_service.list_orders(
            period=period_key, status_filter=status
        )
        return {"items": orders}

    @app.get(
        "/admin/api/orders/{order_id}", dependencies=[Depends(_require_admin)]
    )
    async def order_api(order_id: UUID) -> dict:
        """Return order card as JSON."""
        order = await dashboard_service.get_order_card(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        return order


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

    column_list = [
        UserModel.user_id,
        UserModel.external_id,
        UserModel.messenger_type,
        UserModel.username,
        UserModel.telegram,
        UserModel.status,
        UserModel.admin,
        UserModel.issue_count,
        UserModel.created_at,
    ]
    form_columns = [
        UserModel.admin,
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
                                "external_id": user.external_id,
                                "username": user.username,
                                "previous_status": old_status.value
                                if old_status
                                else None,
                                "event_type": "user.blocked.admin",
                            },
                        )
            except Exception:
                # If logging fails, don't break the update
                pass

        return result


class BloggerProfileAdmin(ModelView, model=BloggerProfileModel):
    """Admin view for blogger profiles."""

    column_list = [
        BloggerProfileModel.user_id,
        BloggerProfileModel.instagram_url,
        BloggerProfileModel.confirmed,
        BloggerProfileModel.city,
        BloggerProfileModel.audience_gender,
        BloggerProfileModel.audience_age_min,
        BloggerProfileModel.audience_age_max,
        BloggerProfileModel.audience_geo,
        BloggerProfileModel.price,
        BloggerProfileModel.barter,
        BloggerProfileModel.work_format,
        BloggerProfileModel.updated_at,
    ]


class AdvertiserProfileAdmin(ModelView, model=AdvertiserProfileModel):
    """Admin view for advertiser profiles."""

    column_list = [
        AdvertiserProfileModel.user_id,
        AdvertiserProfileModel.contact,
        AdvertiserProfileModel.brand,
        AdvertiserProfileModel.city,
        AdvertiserProfileModel.company_activity,
        AdvertiserProfileModel.site_link,
    ]


class OrderAdmin(ModelView, model=OrderModel):
    """Admin view for orders with moderation support."""

    column_list = [
        OrderModel.order_id,
        OrderModel.advertiser_id,
        OrderModel.product_link,
        OrderModel.offer_text,
        OrderModel.price,
        OrderModel.bloggers_needed,
        OrderModel.content_usage,
        OrderModel.deadlines,
        OrderModel.geography,
        OrderModel.status,
        OrderModel.created_at,
    ]
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
        OrderModel.product_photo_file_id,
    ]

    async def update_model(self, request: Request, pk: str, data: dict):
        """Update order with banned content check and activation publishing."""
        pk_uuid = UUID(pk)
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

        obj = await _get_obj_by_pk(self, OrderModel, pk_uuid)
        new_status = obj.status if obj else None

        if (
            old_status != OrderStatus.ACTIVE
            and new_status == OrderStatus.ACTIVE
        ):
            try:
                container = _get_admin_container()
                if container:
                    _, outbox_publisher, order_repo = (
                        _get_order_moderation_deps(container)
                    )
                    tm = container.transaction_manager
                    if tm:
                        async with tm.transaction() as session:
                            order = await order_repo.get_by_id(
                                pk_uuid, session=session
                            )
                            if order:
                                await outbox_publisher.publish_order_activation(
                                    order, session=session
                                )
            except Exception:
                logger.exception(
                    "Failed to publish order activation after admin approval",
                    extra={"order_id": str(pk_uuid)},
                )

        return result


class OrderResponseAdmin(ModelView, model=OrderResponseModel):
    """Admin view for order responses."""

    column_list = [
        OrderResponseModel.response_id,
        OrderResponseModel.order_id,
        OrderResponseModel.blogger_id,
        OrderResponseModel.responded_at,
    ]


class InteractionAdmin(ModelView, model=InteractionModel):
    """Admin view for interactions."""

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
    form_columns = [
        InteractionModel.status,
    ]

    async def update_model(self, request: Request, pk: str, data: dict):
        """Update interaction model with manual issue resolution."""

        pk_uuid = UUID(pk)
        obj = await _get_obj_by_pk(self, InteractionModel, pk_uuid)
        old_status = obj.status if obj else None

        result = await super().update_model(request, pk, data)

        obj = await _get_obj_by_pk(self, InteractionModel, pk_uuid)
        new_status = obj.status if obj else None

        # If manually resolving ISSUE to OK or NO_DEAL
        if old_status == InteractionStatus.ISSUE and new_status in (
            InteractionStatus.OK,
            InteractionStatus.NO_DEAL,
        ):
            try:
                container = _get_admin_container()
                if container:
                    _, _, interaction_service = _get_services(container)
                    await interaction_service.manually_resolve_issue(
                        UUID(pk), new_status
                    )
            except Exception:
                # If service call fails, the status change is already saved
                pass

        return result


class InstagramVerificationAdmin(
    ModelView, model=InstagramVerificationCodeModel
):
    """Admin view for Instagram verification codes."""

    column_list = [
        InstagramVerificationCodeModel.code_id,
        InstagramVerificationCodeModel.user_id,
        InstagramVerificationCodeModel.code,
        InstagramVerificationCodeModel.expires_at,
        InstagramVerificationCodeModel.used,
    ]


class ComplaintAdmin(ModelView, model=ComplaintModel):
    """Admin view for complaints."""

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
                # If service call fails, the status change is already saved
                pass
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
                # If service call fails, the status change is already saved
                pass

        return result


class ContactPricingAdmin(ModelView, model=ContactPricingModel):
    """Admin view for contact pricing."""

    column_list = [
        ContactPricingModel.bloggers_count,
        ContactPricingModel.price,
        ContactPricingModel.updated_at,
    ]
    form_columns = [
        ContactPricingModel.bloggers_count,
        ContactPricingModel.price,
    ]


def _generate_referral_code() -> str:
    """Generate a unique 8-char referral code."""
    import secrets

    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


class ManagerAdmin(ModelView, model=ManagerModel):
    """Admin view for referral managers."""

    name = "Менеджеры"
    column_list = [
        ManagerModel.manager_id,
        ManagerModel.user_id,
        ManagerModel.referral_code,
        ManagerModel.name,
        ManagerModel.created_at,
    ]
    form_columns = [
        ManagerModel.user_id,
        ManagerModel.name,
    ]

    async def insert_model(self, request: Request, data: dict):
        """Insert manager with auto-generated referral code."""
        data["referral_code"] = _generate_referral_code()
        return await super().insert_model(request, data)


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


def create_admin_app() -> FastAPI:  # noqa: C901
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

    @app.get("/health")
    async def health() -> dict[str, bool | str]:
        """Lightweight health check for admin app."""

        db_ok = True
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "db": db_ok}

    auth = AdminAuth(
        secret_key=config.admin.admin_secret,
        username=config.admin.admin_username,
        password=config.admin.admin_password,
    )
    dashboard_service = _build_dashboard_service(config, container)
    templates = _build_templates(app)
    _register_dashboard_routes(app, auth, dashboard_service, templates)
    admin = EnumAwareAdmin(
        app, engine, authentication_backend=auth, base_url="/admin"
    )

    # Store container for service access in admin views
    global _admin_container
    _admin_container = container

    admin.add_view(UserAdmin)
    admin.add_view(ManagerAdmin)
    admin.add_view(BloggerProfileAdmin)
    admin.add_view(AdvertiserProfileAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(OrderResponseAdmin)
    admin.add_view(InteractionAdmin)
    admin.add_view(InstagramVerificationAdmin)
    admin.add_view(ComplaintAdmin)
    admin.add_view(ContactPricingAdmin)

    return app


app = create_admin_app()
