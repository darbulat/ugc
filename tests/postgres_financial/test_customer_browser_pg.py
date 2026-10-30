"""Browser-to-PostgreSQL customer smoke test with a synthetic native host."""

import asyncio
import io
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import UUID

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from PIL import Image
from playwright.async_api import async_playwright, expect
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_order_intake import intake_env as intake_env
from ugc_bot.config import MaxBotConfig
from ugc_bot.infrastructure.db.customer_workflow_models import JOBS, REQUESTS
from ugc_bot.infrastructure.db.models import OrderModel, UserModel
from ugc_bot.infrastructure.db.order_image_models import IMAGES
from ugc_bot.infrastructure.db.repositories.customer_workflows import (
    SqlAlchemyCustomerWorkflowRepository,
)
from ugc_bot.miniapp.api import router

__all__ = ["intake_env"]


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.timeout(90)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_customer_creates_order_with_image_in_browser_and_postgres(
    intake_env, monkeypatch, tmp_path, platform
):
    env = intake_env
    monkeypatch.setenv("ORDER_IMAGE_DIRECTORY", str(tmp_path / "images"))
    env["config"].max_bot = MaxBotConfig.model_validate(
        {"MAX_BOT_TOKEN": "test-token"}
    )
    env["config"].bot.telegram_provider_token = "synthetic-provider"
    env["config"].bot.telegram_payment_account_id = "synthetic-account"
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["user"].user_id)
            .values(max_id=env["user"].telegram_id)
        )
    app = FastAPI()
    app.state.config = env["config"]
    app.state.dispatcher = env["container"].build_bot_services()
    app.state.bot = SimpleNamespace(
        create_invoice_link=AsyncMock(
            return_value="https://t.me/$synthetic_invoice"
        )
    )
    app.include_router(router, prefix="/miniapp")
    static_dir = Path(__file__).resolve().parents[2] / "src/ugc_bot/miniapp"
    app.mount("/miniapp", StaticFiles(directory=static_dir), name="miniapp")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", lifespan="off")
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.05)
        assert server.started
        user = env["user"]
        signed = generate_init_data("test-token", int(user.telegram_id), "test")
        mock = (
            Path(__file__).resolve().parents[1] / "e2e/miniapp_host_mock.js"
        ).read_text()
        mock = mock.replace("__PLATFORM__", json.dumps(platform))
        mock = mock.replace("__NATIVE__", json.dumps(False))
        mock = mock.replace("__INIT_DATA__", json.dumps(signed))
        image = io.BytesIO()
        Image.new("RGB", (1080, 1080), "navy").save(image, format="JPEG")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page(
                viewport={"width": 390, "height": 844}
            )
            await page.add_init_script(script=mock)

            async def local_only(route):
                if urlsplit(route.request.url).hostname == "127.0.0.1":
                    await route.continue_()
                else:
                    await route.abort()

            await page.route("**/*", local_only)
            template = "max_app.html" if platform == "max" else "app.html"
            await page.goto(f"http://127.0.0.1:{port}/miniapp/{template}")
            await expect(page.locator("#btn-show-create-order")).to_be_visible()
            await page.locator("#btn-show-create-order").click()
            await page.locator("#intake-count").fill("10")
            await page.locator("#intake-policy").select_option(env["policy"])
            await page.locator("#intake-product").fill(
                "https://example.test/product"
            )
            await page.locator("#intake-brief").fill(
                "Synthetic complete requested brief"
            )
            await page.locator("#intake-honorarium").fill("999.00")
            await page.locator("#intake-contact").fill("@synthetic_client")
            due = datetime.now(timezone.utc) + timedelta(days=3)
            await page.locator("#intake-due").fill(
                due.strftime("%Y-%m-%dT%H:%M")
            )
            await page.locator(
                'input[name="intake-mode"][value="with_manager"]'
            ).check()
            await page.locator("#intake-order-type").select_option("stories")
            await page.locator("#intake-image").set_input_files(
                {
                    "name": "brief.jpg",
                    "mimeType": "image/jpeg",
                    "buffer": image.getvalue(),
                }
            )
            await expect(page.locator("#intake-image-preview")).to_be_visible()
            async with page.expect_response(
                lambda r: (
                    r.url.endswith("/financial/orders")
                    and r.request.method == "POST"
                )
            ) as pending:
                await page.locator("#btn-intake-create").click()
            response = await pending.value
            body = await response.json()
            assert response.status == 200, body
            await expect(page.locator("#intake-result")).to_be_visible()
            await expect(page.locator("#intake-total")).to_have_attribute(
                "data-minor", "1700000"
            )
            assert body["total_minor"] == 1700000
            assert len(body["items"]) == 10
            if platform == "telegram":
                action = page.locator("#umc-checkout-action")
                await expect(action).to_have_text("Подготовить счёт")
                async with page.expect_response(
                    lambda r: (
                        r.url.endswith("/invoice")
                        and r.request.method == "POST"
                    )
                ) as pending_invoice:
                    await action.click()
                invoice_response = await pending_invoice.value
                invoice = await invoice_response.json()
                assert invoice_response.status == 200, invoice
                assert invoice["invoice_state"] == "ready"
                assert invoice["amount_minor"] == 1700000
                assert app.state.bot.create_invoice_link.await_count == 1
                prices = app.state.bot.create_invoice_link.await_args.kwargs[
                    "prices"
                ]
                assert [price.amount for price in prices] == [500000, 1200000]
                await expect(action).to_have_text("Оплатить в Telegram")
            with Session(env["pg"]) as db:
                order = db.scalar(
                    select(OrderModel).where(
                        OrderModel.order_id == UUID(body["order_id"])
                    )
                )
                assert order is not None and order.advertiser_id == user.user_id
                assert order.order_type.value == "stories"
                stored = (
                    db.execute(
                        select(IMAGES).where(
                            IMAGES.c.order_id == order.order_id
                        )
                    )
                    .mappings()
                    .one()
                )
                assert stored["owner_id"] == user.user_id
                assert stored["byte_count"] == len(image.getvalue())
                assert (
                    tmp_path / "images" / f"{stored['token']}.jpg"
                ).read_bytes() == image.getvalue()
            await page.evaluate("window.UMCCustomer.orders()")
            card = page.locator(f'[data-order-id="{body["order_id"]}"]')
            await expect(card).to_be_visible()
            await card.get_by_role("button", name="Сообщить о проблеме").click()
            await page.locator('#screen-customer-support [name="reason"]').fill(
                "Synthetic support request"
            )
            await page.locator(
                '#screen-customer-support [name="contact"]'
            ).fill("@synthetic_client")
            async with page.expect_response(
                lambda r: (
                    r.url.endswith("/customer/support")
                    and r.request.method == "POST"
                )
            ) as pending_support:
                await page.locator(
                    "#screen-customer-support button[type=submit]"
                ).click()
            response = await pending_support.value
            support = await response.json()
            assert response.status == 200, support
            with Session(env["pg"]) as db:
                request = (
                    db.execute(
                        select(REQUESTS).where(
                            REQUESTS.c.request_id == UUID(support["request_id"])
                        )
                    )
                    .mappings()
                    .one()
                )
                assert request["order_id"] == UUID(body["order_id"])
                assert request["user_id"] == user.user_id
                assert (
                    request["payload"]["reason"] == "Synthetic support request"
                )
                # The persisted request is the durable outbox source; the
                # scheduler expands it into per-recipient delivery jobs.
                assert request["expanded_at"] is None
            async with env["container"].transaction_manager.transaction() as db:
                await SqlAlchemyCustomerWorkflowRepository().expand_admin(
                    datetime.now(timezone.utc), session=db
                )
            with Session(env["pg"]) as db:
                assert db.execute(
                    select(JOBS).where(
                        JOBS.c.request_id == request["request_id"]
                    )
                ).first()
            await browser.close()
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        sock.close()
