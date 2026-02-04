"""SQLAdmin application setup."""

import asyncio
import logging
from typing import TypeVar
from uuid import UUID

from fastapi import FastAPI
from sqladmin import Admin, ModelView
from starlette.requests import Request
from sqlalchemy import text

from ugc_bot.admin.auth import AdminAuth
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import load_config
from ugc_bot.container import Container
from ugc_bot.domain.enums import ComplaintStatus, InteractionStatus, UserStatus
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ComplaintModel,
    ContactPricingModel,
    InstagramVerificationCodeModel,
    InteractionModel,
    OrderModel,
    OrderResponseModel,
    UserModel,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


def _get_services(
    container: Container,
) -> tuple[UserRoleService, ComplaintService, InteractionService]:
    """Get services for admin actions."""
    return container.build_admin_services()


T = TypeVar("T")


async def _get_obj_by_pk(
    view: ModelView,
    model_cls: type[T],
    pk: UUID,
) -> T | None:
    """Get model instance by pk, supporting both sync and async session makers."""
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
        UserModel.issue_count,
        UserModel.created_at,
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
                container = getattr(self, "_container", None)  # type: ignore[attr-defined]
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
    """Admin view for orders."""

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
                container = getattr(self, "_container", None)  # type: ignore[attr-defined]
                if container:
                    _, _, interaction_service = _get_services(container)
                    await interaction_service.manually_resolve_issue(
                        UUID(pk), new_status
                    )
            except Exception:
                # If service call fails, the status change is already saved
                pass

        return result


class InstagramVerificationAdmin(ModelView, model=InstagramVerificationCodeModel):
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
                container = getattr(self, "_container", None)  # type: ignore[attr-defined]
                if container:
                    user_role_service, complaint_service, _ = _get_services(container)
                    # Update complaint status via service (sets reviewed_at)
                    await complaint_service.resolve_complaint_with_action(UUID(pk))
                    # Block the reported user
                    await user_role_service.update_status(
                        reported_id, UserStatus.BLOCKED
                    )
            except Exception:
                # If service call fails, the status change is already saved
                pass
        elif old_status != new_status and new_status == ComplaintStatus.DISMISSED:
            try:
                container = getattr(self, "_container", None)  # type: ignore[attr-defined]
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
    admin = Admin(app, engine, authentication_backend=auth, base_url="/admin")

    # Store container in admin views for service access
    UserAdmin._container = container  # type: ignore[attr-defined]
    InteractionAdmin._container = container  # type: ignore[attr-defined]
    ComplaintAdmin._container = container  # type: ignore[attr-defined]

    admin.add_view(UserAdmin)
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
