"""Signed JPEG upload and order binding use production factories and SQL."""

import base64
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.application.services.test_order_image_service import picture
from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_user,
)
from tests.postgres_financial.test_order_intake import intake_env as _intake_env
from tests.postgres_financial.test_order_intake_api import app, body
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.order_image_models import IMAGES
from ugc_bot.infrastructure.order_images import image_path


@pytest_asyncio.fixture
async def intake_env(financial_pg_engine):
    async for value in _intake_env.__wrapped__(financial_pg_engine):
        yield value


@pytest.mark.asyncio
async def test_signed_image_create_replay_and_scope(
    intake_env, tmp_path, monkeypatch
):
    monkeypatch.setenv("ORDER_IMAGE_DIRECTORY", str(tmp_path))
    env = intake_env
    container = Container(env["config"])
    application = app(env, container)
    signed = body(env)["init_data"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        upload = await client.post(
            "/miniapp/api/orders/images",
            json={
                "init_data": signed,
                "image_base64": base64.b64encode(picture()).decode(),
            },
        )
        assert upload.status_code == 200, upload.text
        assert upload.headers["cache-control"] == "no-store"
        token = upload.json()["image_token"]
        payload = body(env) | {"image_token": token, "position_count": 10}
        first = await client.post("/miniapp/api/financial/orders", json=payload)
        assert first.status_code == 200, first.text
        assert first.json()["public_number"].startswith("UMC-")
        assert len(first.json()["items"]) == 10
        persisted = await container.build_repos()["order_repo"].get_by_id(
            UUID(first.json()["order_id"])
        )
        assert persisted.product_photo_file_id == "order-image:" + token
        view = await client.post(
            "/miniapp/api/financial/orders/"
            + first.json()["order_id"]
            + "/selection",
            json={"init_data": signed},
        )
        assert view.status_code == 200, view.text
        assert view.json()["image_token"] == token
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(IMAGES)
                .where(IMAGES.c.token == UUID(token))
                .values(
                    expires_at=datetime.now(timezone.utc) - timedelta(days=2)
                )
            )
        repeated = await client.post(
            "/miniapp/api/financial/orders", json=payload
        )
        assert repeated.json() == first.json()
        content = await client.post(
            "/miniapp/api/orders/images/content",
            json={"init_data": signed, "image_token": token},
        )
        assert content.status_code == 200
        assert content.headers["cache-control"] == "no-store"
        assert base64.b64decode(content.json()["image_base64"]) == picture()
        other = await create_test_user(
            container.build_repos()["user_repo"],
            external_id=str(uuid4().int % 10**12 + 1),
            country="ru",
        )
        await create_test_advertiser_profile(
            container.build_repos()["advertiser_repo"], other.user_id
        )
        foreign = generate_init_data(
            "test-token", int(other.telegram_id), "other"
        )
        denied = await client.post(
            "/miniapp/api/orders/images/content",
            json={"init_data": foreign, "image_token": token},
        )
        assert denied.status_code == 403
        assert denied.headers["cache-control"] == "no-store"
        forged = await client.post(
            "/miniapp/api/orders/images",
            json={"init_data": "forged", "image_base64": "aaaa"},
        )
        assert forged.status_code == 401
    await container.dispose()


@pytest.mark.asyncio
async def test_image_invalid_request_expiry_and_cleanup(
    intake_env, tmp_path, monkeypatch
):
    monkeypatch.setenv("ORDER_IMAGE_DIRECTORY", str(tmp_path))
    env = intake_env
    container = Container(env["config"])
    application = app(env, container)
    signed = body(env)["init_data"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        for data in ("!!!!", base64.b64encode(picture(kind="PNG")).decode()):
            response = await client.post(
                "/miniapp/api/orders/images",
                json={"init_data": signed, "image_base64": data},
            )
            assert response.status_code == 422
            assert response.headers["cache-control"] == "no-store"
        upload = await client.post(
            "/miniapp/api/orders/images",
            json={
                "init_data": signed,
                "image_base64": base64.b64encode(picture()).decode(),
            },
        )
        token = UUID(upload.json()["image_token"])
        assert image_path(token, tmp_path).is_file()
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(IMAGES)
                .where(IMAGES.c.token == token)
                .values(
                    expires_at=datetime.now(timezone.utc) - timedelta(days=2)
                )
            )
        expired = await client.post(
            "/miniapp/api/orders/images/content",
            json={"init_data": signed, "image_token": str(token)},
        )
        assert expired.status_code == 422
        assert (
            await application.state.dispatcher["order_image_service"].cleanup()
            == 1
        )
        assert not image_path(token, tmp_path).exists()
        missing = await client.post(
            "/miniapp/api/orders/images/content",
            json={"init_data": signed, "image_token": str(token)},
        )
        assert missing.status_code == 404
        with Session(env["pg"]) as db:
            assert (
                db.scalar(select(IMAGES.c.token).where(IMAGES.c.token == token))
                is None
            )
    await container.dispose()
