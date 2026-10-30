"""Browser-to-PostgreSQL customer smoke test with a synthetic native host."""

import asyncio
import io
import json
import socket
from dataclasses import replace
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
from fastapi.testclient import TestClient
from PIL import Image
from playwright.async_api import async_playwright, expect
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.fakes import FakeCallback, FakeUser
from tests.postgres_financial.test_order_intake import intake_env as intake_env
from ugc_bot.application.services.checkout_paid_receipts import (
    PaidReceiptProcessor,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.bot.telegram.handlers.admin_moderation import (
    handle_moderate_activate,
)
from ugc_bot.config import MaxBotConfig
from ugc_bot.domain.checkout import NativePaidReceipt
from ugc_bot.infrastructure.db.customer_workflow_models import JOBS, REQUESTS
from ugc_bot.infrastructure.db.models import OrderModel, UserModel
from ugc_bot.infrastructure.db.order_image_models import IMAGES
from ugc_bot.infrastructure.db.repositories.customer_workflows import (
    SqlAlchemyCustomerWorkflowRepository,
)
from ugc_bot.miniapp.api import router

__all__ = ["intake_env"]

_CHECKOUT = {
    "ru": ("Подготовить счёт", "Оплатить в Telegram"),
    "en": ("Prepare invoice", "Pay in Telegram"),
    "kk": ("Шот дайындау", "Telegram арқылы төлеу"),
    "be": ("Падрыхтаваць рахунак", "Аплаціць у Telegram"),
    "uz": ("Hisob tayyorlash", "Telegram orqali to‘lash"),
}
_SUPPORT = {
    "ru": "Сообщить о проблеме",
    "en": "Report a problem",
    "kk": "Мәселе туралы хабарлау",
    "be": "Паведаміць пра праблему",
    "uz": "Muammo haqida xabar berish",
}
_SELECTION_DUE = {
    "ru": "Согласованный срок подбора",
    "en": "Agreed selection due date",
    "kk": "Келісілген іріктеу мерзімі",
    "be": "Узгоднены тэрмін падбору",
    "uz": "Kelishilgan tanlov muddati",
}
_PAYMENT_TOGETHER = {
    "ru": "Подбор и выбранное сопровождение оплачиваются вместе в одном счёте.",
    "en": (
        "Creator selection and chosen management are paid together "
        "in one invoice."
    ),
    "kk": "Іріктеу мен таңдалған сүйемелдеу бір шотпен бірге төленеді.",
    "be": "Падбор і выбранае суправаджэнне аплачваюцца разам у адным рахунку.",
    "uz": "Tanlov va tanlangan hamrohlik bitta hisobda birga to‘lanadi.",
}


async def _capture_and_activate(
    env, app, page, order_id, selection_due_at, image, monkeypatch
):
    """Continue this browser's order through a synthetic provider and admin."""
    from ugc_bot.admin import app as admin_module

    services = app.state.dispatcher
    transactions = env["container"].transaction_manager
    checkout = services["checkout_service"]
    order_id = UUID(order_id)
    await page.wait_for_function(
        "async id => {"
        "const state=await window.__umcAppBridge.request("
        "'/customer/followups/state',{});"
        "return state && state.order_id===id;}",
        arg=str(order_id),
    )
    await expect(page.locator("#customer-followup")).to_have_count(1)

    async def activate():
        callback = FakeCallback(
            data=f"mod_activate:{order_id.hex}",
            user=FakeUser(int(env["admin"].telegram_id), "admin"),
        )
        await handle_moderate_activate(
            callback,
            user_role_service=services["user_role_service"],
            content_moderation_service=ContentModerationService(),
            order_repo=env["repos"]["order_repo"],
            outbox_publisher=services["outbox_publisher"],
            transaction_manager=transactions,
            payment_repo=env["repos"]["payment_repo"],
        )
        return callback.answers

    assert await activate() == ["Заказ уже обработан."]
    async with transactions.transaction() as session:
        await checkout.repository.authorize(
            order_id,
            env["user"].telegram_id,
            "synthetic-precheckout",
            1700000,
            "RUB",
            session=session,
        )
    receipt = NativePaidReceipt(
        env["user"].telegram_id,
        "synthetic-chat",
        "synthetic-message",
        order_id,
        "synthetic-provider-charge",
        "synthetic-telegram-charge",
        1700000,
        "RUB",
        datetime.now(timezone.utc),
    )
    payment = replace(
        services["payment_service"],
        capture_repository=checkout.repository.capture,
        capture_account=env["config"].bot.telegram_payment_account_id,
    )
    processor = PaidReceiptProcessor(checkout.repository, transactions, payment)
    assert await processor.accept(receipt)
    assert await processor.run_once()
    followup = await page.evaluate(
        "() => window.__umcAppBridge.request('/customer/followups/state',{})"
    )
    assert followup["stop_reason"] == "paid"
    assert followup["next_stage"] is None
    await page.locator("#umc-checkout-refresh").click()
    await expect(page.locator("#umc-checkout-status")).to_have_attribute(
        "data-state", "confirmed"
    )
    await expect(page.locator("#customer-followup")).to_have_count(0)

    env["config"].admin.admin_base_url = "https://admin.example.test"
    messenger = AsyncMock()
    notices = env["container"].build_order_notice_delivery(messenger)
    for _ in range(100):
        if not await notices.run_once():
            break
    cards = [call.kwargs for call in messenger.send_photo.await_args_list]
    assert len(cards) == 2
    created = next(card for card in cards if "Новый заказ" in card["caption"])
    paid = next(card for card in cards if "Заказ оплачен" in card["caption"])
    due_display = (
        datetime.fromisoformat(selection_due_at)
        .astimezone(timezone.utc)
        .strftime("%d.%m.%Y %H:%M:%S UTC")
    )
    assert f"Срок подбора:</b> {due_display}" in paid["caption"]
    assert created["chat_id"] == paid["chat_id"] == env["admin"].telegram_id
    assert created["file_id"] == paid["file_id"]
    buttons = [button for row in paid["keyboard"].rows for button in row]
    assert any(
        button.callback_data == f"mod_activate:{order_id.hex}"
        for button in buttons
    )
    target = f"/admin/order-model/edit/{order_id}"
    assert any(
        button.url == "https://admin.example.test" + target
        for button in buttons
    )
    assert not await notices.run_once()

    config = env["config"].model_copy(
        update={
            "admin": env["config"].admin.model_copy(
                update={
                    "admin_username": "admin",
                    "admin_password": "Strong-Image-Preview42!",
                    "admin_secret": (
                        "strong-image-admin-test-secret-32-characters"
                    ),
                }
            )
        }
    )
    monkeypatch.setattr(admin_module, "load_config", lambda: config)
    with TestClient(admin_module.create_admin_app()) as client:
        response = client.get(target, follow_redirects=False)
        assert response.status_code == 302
        assert "/admin/login" in response.headers["location"]
        login = client.post(
            "/admin/login",
            data={"username": "admin", "password": "Strong-Image-Preview42!"},
            follow_redirects=False,
        )
        assert login.status_code == 302
        assert login.headers["location"] == target
        edit = client.get(target)
        assert edit.status_code == 200
        assert due_display in edit.text
        assert client.get(f"/admin/order-images/{order_id}").content == image

    assert await activate() == ["Заказ активирован, уходит блогерам."]
    assert await activate() == ["Заказ уже обработан."]


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.timeout(90)
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
async def test_customer_creates_order_with_image_in_browser_and_postgres(
    intake_env, monkeypatch, tmp_path, platform, locale
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
            .values(max_id=env["user"].telegram_id, language=locale)
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
            await expect(page.locator("html")).to_have_attribute("lang", locale)
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
            await expect(page.locator("#intake-preview")).to_contain_text(
                _PAYMENT_TOGETHER[locale]
            )
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
            await expect(page.locator("#intake-result")).to_contain_text(
                _PAYMENT_TOGETHER[locale]
            )
            await expect(page.locator("#intake-total")).to_have_attribute(
                "data-minor", "1700000"
            )
            assert body["total_minor"] == 1700000
            assert len(body["items"]) == 10
            if platform == "telegram":
                action = page.locator("#umc-checkout-action")
                await expect(action).to_have_text(_CHECKOUT[locale][0])
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
                await expect(action).to_have_text(_CHECKOUT[locale][1])
                if locale == "ru":
                    await page.evaluate(
                        "window.Telegram.WebApp.openInvoice=(url,callback)=>{"
                        "window.__invoiceUrl=url;window.__invoiceCallback=callback}"
                    )
                    await action.click()
                    assert await page.evaluate("window.__invoiceUrl") == (
                        "https://t.me/$synthetic_invoice"
                    )
                    await page.evaluate("window.__invoiceCallback('paid')")
                    await expect(
                        page.locator("#umc-checkout-status")
                    ).not_to_have_attribute("data-state", "confirmed")
                    await _capture_and_activate(
                        env,
                        app,
                        page,
                        body["order_id"],
                        body["selection_due_at"],
                        image.getvalue(),
                        monkeypatch,
                    )
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
            async with page.expect_response(
                lambda r: r.url.endswith("/customer/orders/completion")
            ) as pending_completion:
                await page.locator("#btn-intake-selection").click()
            completion = await pending_completion.value
            assert completion.status == 200, await completion.text()
            assert await completion.json() == {"has_completed_work": False}
            await page.wait_for_function(
                "() => document.querySelector('#screen-selection')"
                ".dataset.recommendationChecked === 'true'"
            )
            await expect(
                page.locator("#screen-selection [data-service-recommendation]")
            ).to_have_count(0)
            await page.evaluate("window.UMCCustomer.orders()")
            card = page.locator(f'[data-order-id="{body["order_id"]}"]')
            await expect(card).to_be_visible()
            displayed_due = await page.evaluate(
                "([date, locale]) => new Date(date).toLocaleString(locale)",
                [body["selection_due_at"], locale],
            )
            await expect(card).to_contain_text(
                f"{_SELECTION_DUE[locale]}: {displayed_due}"
            )
            if platform == "telegram" and locale == "ru":
                await expect(card).to_contain_text("Идёт подбор")
                await expect(card).to_contain_text("Оплачено")
            await card.get_by_role("button", name=_SUPPORT[locale]).click()
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
