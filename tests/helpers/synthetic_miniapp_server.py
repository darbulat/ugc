"""Disposable Mini App for the isolated browser acceptance suite.

Run only against an explicitly marked test database. The server uses a fresh
schema, synthetic identities, a fake payment gateway and a fake geocoder.
"""

import os
import re
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import MINIAPP_TEST_USER_IDS
from tests.helpers.financial_environment import (
    isolated_financial_database,
    require_synthetic_e2e,
    require_test_database,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.models import (
    FinancialPolicyVersionModel,
    UserModel,
)
from ugc_bot.miniapp.api import router


def require_test_app_database(environment: Mapping[str, str]) -> str:
    """Reject unsafe settings before opening any database connection."""
    if environment.get("E2E_TEST_ONLY") != "1":
        raise ValueError("E2E_TEST_ONLY=1 is required")
    url = require_test_database(environment.get("DATABASE_URL"))
    require_synthetic_e2e(
        {
            "E2E_TEST_ONLY": "1",
            "E2E_DATABASE_URL": url,
            "E2E_BOT_TOKEN": environment.get("E2E_BOT_TOKEN", "test-token"),
        }
    )
    return url


def require_private_schema(database_url: str) -> None:
    """Require the exact private search path created by the test helper."""
    try:
        parsed = make_url(database_url)
        require_test_database(
            parsed.set(query={}).render_as_string(hide_password=False)
        )
        options = parsed.query.get("options")
        if set(parsed.query) != {"options"} or not isinstance(options, str):
            raise ValueError("private test schema required")
        if not re.fullmatch(
            r"-csearch_path=financial_test_[a-f0-9]{32},public", options
        ):
            raise ValueError("private test schema required")
    except (ArgumentError, TypeError, ValueError):
        raise ValueError("private test schema required") from None


class SyntheticGeocoder:
    async def geocode_with_details(self, city, **kwargs):
        return 55.7558, 37.6173, None, None, "Test region", "Test country"

    async def reverse_geocode(self, lat, lon):
        return "Test city", "Test region", "Test country"


class SyntheticMessenger:
    async def send_text(self, *args, **kwargs):
        return None


class SyntheticBot:
    async def create_invoice_link(self, **kwargs):
        return "https://t.me/$synthetic_invoice"


def seed(engine) -> None:
    """Seed only the private, freshly migrated schema."""
    require_private_schema(engine.url.render_as_string(hide_password=False))
    now = datetime.now(timezone.utc)
    with Session(engine) as db, db.begin():
        schema = db.scalar(text("SELECT current_schema()"))
        if not re.fullmatch(r"financial_test_[a-f0-9]{32}", schema or ""):
            raise ValueError("private test schema required")
        admin = UserModel(
            user_id=uuid4(),
            telegram_id="990099999",
            messenger_type=MessengerType.TELEGRAM,
            username="synthetic_admin",
            status=UserStatus.ACTIVE,
            admin=True,
        )
        db.add(admin)
        clients = []
        for role, ids in MINIAPP_TEST_USER_IDS.items():
            for locale, external_id in ids.items():
                user = UserModel(
                    user_id=uuid4(),
                    telegram_id=str(external_id),
                    messenger_type=MessengerType.TELEGRAM,
                    username=f"synthetic_{role}_{locale}",
                    status=UserStatus.ACTIVE,
                )
                db.add(user)
                if role == "advertiser":
                    clients.append(str(user.user_id))
        db.flush()
        db.add(
            FinancialPolicyVersionModel(
                version="synthetic-e2e-v1",
                approved_by=admin.user_id,
                approved_at=now - timedelta(days=2),
                effective_from=now - timedelta(days=1),
                refund_window_seconds=86400,
                rules={
                    "terms_reference": "https://example.test/terms",
                    "allowed_clients": clients,
                },
            )
        )


def build_test_config(database_url: str) -> AppConfig:
    """Do not load the developer's environment or local .env into the app."""
    require_private_schema(database_url)
    with TemporaryDirectory(prefix="umc-e2e-config-") as empty_dir:
        previous_dir = os.getcwd()
        try:
            os.chdir(empty_dir)
            with patch.dict(os.environ, {}, clear=True):
                return AppConfig.model_validate(
                    {
                        "BOT_TOKEN": "test-token",
                        "MAX_BOT_TOKEN": "",
                        "DATABASE_URL": database_url,
                        "KAFKA_ENABLED": False,
                        "USE_REDIS_STORAGE": False,
                        "REDIS_URL": "",
                        "FINANCIAL_CORE_ENABLED": True,
                        "FINANCIAL_NEW_ORDERS_ENABLED": True,
                        "TELEGRAM_PROVIDER_TOKEN": "synthetic-provider",
                        "TELEGRAM_PAYMENT_ACCOUNT_ID": "synthetic-account",
                    }
                )
        finally:
            os.chdir(previous_dir)


def create_app(database_url: str) -> FastAPI:
    config = build_test_config(database_url)
    container = Container(config)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await container.session_factory.kw["bind"].dispose()

    app = FastAPI(lifespan=lifespan)
    app.state.config = config
    app.state.dispatcher = container.build_bot_services()
    app.state.dispatcher[
        "blogger_registration_service"
    ].geocoder = SyntheticGeocoder()
    app.state.dispatcher["messenger_client"] = SyntheticMessenger()
    app.state.bot = SyntheticBot()
    app.include_router(router, prefix="/miniapp")
    static = Path(__file__).resolve().parents[2] / "src/ugc_bot/miniapp"
    app.mount("/miniapp", StaticFiles(directory=static), name="miniapp")
    return app


def main() -> None:
    database_url = require_test_app_database(os.environ)
    host = os.environ.get("SYNTHETIC_E2E_BIND", "127.0.0.1")
    if host not in ("127.0.0.1", "0.0.0.0"):
        raise ValueError("invalid test server bind address")
    with (
        TemporaryDirectory(prefix="umc-e2e-images-") as images,
        isolated_financial_database(database_url) as engine,
    ):
        os.environ["ORDER_IMAGE_DIRECTORY"] = images
        seed(engine)
        scoped = engine.url.render_as_string(hide_password=False)
        uvicorn.run(create_app(scoped), host=host, port=8002)


if __name__ == "__main__":
    main()
