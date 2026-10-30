"""The customer sees a completed collaboration through real browser and SQL."""

import asyncio
import json
import socket
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright, expect
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_v1_capture import capture_env as capture_env
from tests.postgres_financial.test_work_entitlement_runtime import start_flow
from ugc_bot.config import MaxBotConfig
from ugc_bot.domain.enums import InteractionStatus, OrderStatus, RaterRole
from ugc_bot.infrastructure.db.customer_workflow_models import REQUESTS
from ugc_bot.infrastructure.db.models import (
    BloggerRatingModel,
    InteractionModel,
    OrderModel,
    UserModel,
)
from ugc_bot.miniapp.api import router

__all__ = ["capture_env"]


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.timeout(90)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_completed_work_enables_rating_and_ambassador_request(
    capture_env, monkeypatch, platform
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    external_id = str(uuid4().int % 10**12 + 1)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["client"])
            .values(
                telegram_id=external_id,
                max_id=external_id,
                country="ru",
                language="ru",
            )
        )
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == env["order"])
            .values(product_link="https://example.test/old-order")
        )
    config = flow["container"]._config
    config.max_bot = MaxBotConfig.model_validate(
        {"MAX_BOT_TOKEN": "test-token"}
    )
    app = FastAPI()
    app.state.config = config
    app.state.dispatcher = flow["container"].build_bot_services()
    app.state.bot = SimpleNamespace(create_invoice_link=AsyncMock())
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
        signed = generate_init_data("test-token", int(external_id), "test")
        mock = (
            Path(__file__).resolve().parents[1] / "e2e/miniapp_host_mock.js"
        ).read_text()
        mock = mock.replace("__PLATFORM__", json.dumps(platform))
        mock = mock.replace("__NATIVE__", json.dumps(False))
        mock = mock.replace("__INIT_DATA__", json.dumps(signed))
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page(
                viewport={"width": 390, "height": 844}
            )
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.add_init_script(script=mock)
            script_requested = asyncio.Event()
            release_script = asyncio.Event()
            startup_complete = asyncio.Event()
            startup_paths = {"/miniapp/api/me", "/miniapp/api/config"}
            startup_seen = set()

            def record_startup(response):
                path = urlsplit(response.url).path
                if path in startup_paths and response.status == 200:
                    startup_seen.add(path)
                    if startup_seen == startup_paths:
                        startup_complete.set()

            page.on("response", record_startup)

            async def local_only(route):
                if urlsplit(route.request.url).hostname == "127.0.0.1":
                    if urlsplit(route.request.url).path.endswith(
                        "/umc-order-images.js"
                    ):
                        script_requested.set()
                        await release_script.wait()
                    await route.continue_()
                else:
                    await route.abort()

            await page.route("**/*", local_only)
            template = "max_app.html" if platform == "max" else "app.html"
            navigation = asyncio.create_task(
                page.goto(
                    f"http://127.0.0.1:{port}/miniapp/{template}?selection={env['order']}",
                    wait_until="domcontentloaded",
                )
            )
            try:
                await asyncio.wait_for(script_requested.wait(), timeout=10)
                await asyncio.wait_for(startup_complete.wait(), timeout=10)
                await page.wait_for_function(
                    "() => Boolean(window.UMCSelection)", timeout=10000
                )
                with suppress(PlaywrightTimeoutError):
                    # Without the startup barrier this renders before later
                    # consumers have subscribed to the selection event.
                    await page.wait_for_selector(
                        "#selection-positions article", timeout=2000
                    )
            finally:
                release_script.set()
                await navigation
            await page.wait_for_function(
                "() => document.querySelector('#screen-selection')"
                ".dataset.recommendationChecked === 'true'",
                timeout=5000,
            )
            recommendation = page.locator(
                "#screen-selection [data-service-recommendation]"
            )
            await expect(recommendation).to_have_count(0)
            await page.evaluate(
                "id => UMCCustomer.ratings(id)", str(env["order"])
            )
            ratings = page.locator("#screen-customer-ratings")
            await expect(ratings.locator("article")).to_have_count(1)
            await expect(ratings.locator("form")).to_have_count(0)

            await flow["command"]("start", env["client"], 1)
            await flow["command"](
                "claim", flow["creator"], 2, evidence="Synthetic work"
            )
            await flow["command"]("agree", env["client"], 3)
            async with page.expect_response(
                lambda response: response.url.endswith(
                    "/customer/orders/completion"
                )
            ) as pending:
                await page.evaluate(
                    "id => UMCSelection.open(id)", str(env["order"])
                )
            response = await pending.value
            assert response.status == 200
            assert await response.json() == {"has_completed_work": True}
            await expect(recommendation).to_be_visible()
            await recommendation.click()
            service = page.locator("#screen-customer-services")
            await service.locator('[name="contact"]').fill(
                "@synthetic_customer"
            )
            await service.locator('input[type="checkbox"]').check()
            await service.locator('button[type="submit"]').click()
            await expect(service).to_contain_text("Заявка сохранена")
            with Session(env["pg"]) as db:
                lead = (
                    db.execute(
                        select(REQUESTS).where(
                            REQUESTS.c.order_id == env["order"]
                        )
                    )
                    .mappings()
                    .one()
                )
                assert lead["user_id"] == env["client"]
                assert lead["payload"]["service_code"] == "ambassadors"

            await page.evaluate(
                "id => UMCCustomer.ratings(id)", str(env["order"])
            )
            await expect(ratings.locator("form")).to_have_count(1)
            await ratings.locator("select").select_option("4")
            await ratings.locator("textarea").fill("Хорошая работа")
            await ratings.locator('button[type="submit"]').click()
            await expect(ratings).to_contain_text("Оценка сохранена")
            with Session(env["pg"]) as db:
                row = db.scalar(
                    select(BloggerRatingModel).where(
                        BloggerRatingModel.order_id == env["order"],
                        BloggerRatingModel.blogger_id == flow["creator"],
                    )
                )
                assert row is not None
                assert (row.rater_id, row.score, row.comment) == (
                    env["client"],
                    4,
                    "Хорошая работа",
                )

            legacy_order, legacy_interaction = uuid4(), uuid4()
            with Session(env["pg"]) as db, db.begin():
                db.add(
                    OrderModel(
                        order_id=legacy_order,
                        advertiser_id=env["client"],
                        product_link="https://example.test/legacy-product",
                        offer_text="Active legacy order",
                        price=1000,
                        bloggers_needed=10,
                        status=OrderStatus.ACTIVE,
                    )
                )
                db.flush()
                db.add(
                    InteractionModel(
                        interaction_id=legacy_interaction,
                        order_id=legacy_order,
                        blogger_id=flow["creator"],
                        advertiser_id=env["client"],
                        status=InteractionStatus.PENDING,
                    )
                )
            await page.evaluate("UMCCustomer.orders()")
            card = page.locator(f'[data-order-id="{legacy_order}"]')
            await expect(card).to_be_visible()
            await expect(
                card.get_by_role("button", name="Оценить автора")
            ).to_have_count(0)
            with Session(env["pg"]) as db, db.begin():
                db.execute(
                    update(InteractionModel)
                    .where(
                        InteractionModel.interaction_id == legacy_interaction
                    )
                    .values(status=InteractionStatus.OK)
                )
            await (
                page.locator("#screen-customer-orders")
                .get_by_role("button", name="Обновить статусы")
                .click()
            )
            await expect(
                card.get_by_role("button", name="Оценить автора")
            ).to_be_visible()
            await card.get_by_role("button", name="Оценить автора").click()
            await expect(ratings.locator("form")).to_have_count(1)
            await ratings.locator("select").select_option("3")
            await ratings.locator('button[type="submit"]').click()
            await expect(ratings).to_contain_text("Оценка сохранена")
            with Session(env["pg"]) as db:
                legacy_rating = db.scalar(
                    select(BloggerRatingModel).where(
                        BloggerRatingModel.order_id == legacy_order,
                        BloggerRatingModel.blogger_id == flow["creator"],
                    )
                )
                assert legacy_rating is not None
                assert legacy_rating.rater_id == env["client"]
                assert legacy_rating.score == 3

            closed_order = uuid4()
            with Session(env["pg"]) as db, db.begin():
                db.add(
                    OrderModel(
                        order_id=closed_order,
                        advertiser_id=env["client"],
                        product_link="https://example.test/closed-legacy",
                        offer_text="Closed legacy order",
                        price=1000,
                        bloggers_needed=10,
                        status=OrderStatus.CLOSED,
                    )
                )
                db.flush()
                db.add(
                    InteractionModel(
                        interaction_id=uuid4(),
                        order_id=closed_order,
                        blogger_id=flow["creator"],
                        advertiser_id=env["client"],
                        status=InteractionStatus.PENDING,
                    )
                )
                db.add(
                    BloggerRatingModel(
                        rating_id=uuid4(),
                        order_id=closed_order,
                        blogger_id=flow["creator"],
                        rater_id=flow["manager"],
                        rater_role=RaterRole.MANAGER,
                        score=4,
                        comment="Сохранённая оценка менеджера",
                    )
                )
            await page.evaluate("UMCCustomer.orders()")
            closed = page.locator(f'[data-order-id="{closed_order}"]')
            await expect(closed).to_be_visible()
            await closed.get_by_role("button", name="Оценить автора").click()
            await expect(ratings).to_contain_text("Оценка менеджера")
            await expect(ratings).to_contain_text(
                "Сохранённая оценка менеджера"
            )
            await expect(ratings.locator("form")).to_have_count(0)
            assert not errors
            await browser.close()
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        sock.close()
        await flow["container"].dispose()
