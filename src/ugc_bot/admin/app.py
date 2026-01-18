"""FastAPI Admin application setup."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi_admin.app import app as admin_app  # type: ignore[import-untyped]
from fastapi_admin.providers.login import (  # type: ignore[import-untyped]
    UsernamePasswordProvider,
)
from fastapi_admin.resources import Model  # type: ignore[import-untyped]
from fastapi_admin.utils import hash_password  # type: ignore[import-untyped]
from redis.asyncio import from_url as redis_from_url
from tortoise import Tortoise

from ugc_bot.admin.config import build_async_database_url
from ugc_bot.admin.models import (
    Admin,
    AdvertiserProfile,
    BloggerProfile,
    Complaint,
    InstagramVerificationCode,
    Interaction,
    Order,
    OrderResponse,
    User,
)
from ugc_bot.config import load_config


logger = logging.getLogger(__name__)


def create_admin_app() -> FastAPI:
    """Create a FastAPI app with mounted admin panel."""

    app = FastAPI(title="UGC Admin")
    app.mount("/admin", admin_app)
    return app


@admin_app.on_event("startup")
async def startup() -> None:
    """Configure admin panel and init ORM."""

    config = load_config()
    if not config.redis_url:
        raise ValueError("REDIS_URL is required for admin panel.")
    if not config.admin_secret:
        raise ValueError("ADMIN_SECRET is required for admin panel.")
    if not config.admin_password:
        raise ValueError("ADMIN_PASSWORD is required for admin panel.")

    async_db_url = build_async_database_url(
        config.database_url, config.admin_database_url
    )
    await Tortoise.init(
        db_url=async_db_url,
        modules={"models": ["ugc_bot.admin.models"]},
    )
    await Tortoise.generate_schemas(safe=True)

    await Admin.get_or_create(
        username=config.admin_username,
        defaults={"password": hash_password(config.admin_password)},
    )

    redis = await redis_from_url(config.redis_url, decode_responses=True)
    await admin_app.configure(
        logo_url="https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png",
        secret_key=config.admin_secret,
        providers=[
            UsernamePasswordProvider(
                admin_model=Admin,
                login_logo_url="https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png",
            )
        ],
        redis=redis,
        resources=[
            Model(User),
            Model(BloggerProfile),
            Model(AdvertiserProfile),
            Model(Order),
            Model(OrderResponse),
            Model(Interaction),
            Model(InstagramVerificationCode),
            Model(Complaint),
        ],
    )


app = create_admin_app()
