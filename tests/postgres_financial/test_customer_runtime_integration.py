"""Production customer factories and synthetic providers."""

from datetime import timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.postgres_financial.test_order_intake import (
    command,
    service,
)
from tests.postgres_financial.test_order_intake import (
    intake_env as _intake_env,
)
from ugc_bot.application.customer_offer_texts import offer_text
from ugc_bot.application.notice_delivery_ports import DeliveryReceipt
from ugc_bot.container.customer_workflow_factory import (
    build_customer_workflow_delivery,
    build_customer_workflows,
)
from ugc_bot.domain.customer_workflows import SupportInput
from ugc_bot.infrastructure.db.customer_workflow_models import JOBS
from ugc_bot.infrastructure.db.repositories.order_notice_details import (
    SqlAlchemyOrderNoticeDetailsRepository,
)


@pytest_asyncio.fixture
async def intake_env(financial_pg_engine):
    async for env in _intake_env.__wrapped__(financial_pg_engine):
        yield env


@pytest.mark.asyncio
async def test_default_off_delivers_admin_work_without_consuming_followups(
    intake_env,
):
    env = intake_env
    transactions = env["container"].transaction_manager
    workflows = build_customer_workflows(transactions, env["clock"])
    result = await service(env).create(command(env, position_count=10))
    await workflows["client_followup_service"].record_activity(
        env["user"].user_id, "menu"
    )
    env["clock"].at += timedelta(hours=1, seconds=1)
    worker = build_customer_workflow_delivery(
        env["config"], transactions, AsyncMock()
    )
    worker.clock = env["clock"]
    worker.action_urls["telegram"] = "https://example.test/miniapp/app.html"
    assert worker.followups_enabled is False
    with Session(env["pg"]) as db:
        before = [dict(row) for row in db.execute(select(JOBS)).mappings()]
    await workflows["order_support_service"].create(
        env["user"].user_id,
        SupportInput(
            order_id=result.order_id,
            operation_key="support-with-sales-disabled",
            reason="Please help with publication",
            contact_reference="@protected-client",
        ),
    )
    transport = AsyncMock()
    transport.send.return_value = DeliveryReceipt("telegram", "synthetic:ok")
    worker.transport = transport
    assert await worker.run_once() >= 1
    with Session(env["pg"]) as db:
        after = [dict(row) for row in db.execute(select(JOBS)).mappings()]
    followups = [row for row in after if row["series_id"]]
    assert followups == before
    assert all(
        call.args[0].action_url is None
        for call in transport.send.call_args_list
    )
    worker.followups_enabled = True
    assert (
        await worker.offer_loader(
            dict(user_id=env["user"].user_id, order_id=None)
        )
        is not None
    )
    assert await worker.run_once() == 1
    assert "5000 RUB" in transport.send.call_args.args[0].text
    assert "500 RUB" in transport.send.call_args.args[0].text


@pytest.mark.asyncio
async def test_saved_notice_details_and_followup_never_reprice_issued_quote(
    intake_env,
):
    env = intake_env
    transactions = env["container"].transaction_manager
    request = command(
        env,
        position_count=10,
        service_mode="with_manager",
        accompaniment_ordinals=frozenset({1, 2}),
    )
    result = await service(env).create(request)
    # Environment tariffs cannot replace the immutable quote components.
    object.__setattr__(env["config"].financial, "selection_price_minor", 777777)
    async with transactions.transaction() as session:
        saved = await SqlAlchemyOrderNoticeDetailsRepository().load(
            result.order_id, session=session
        )
    assert saved["contact_reference"] == request.contact_reference
    assert saved["selection_due_at"] == result.selection_due_at.isoformat()
    due_display = result.selection_due_at.astimezone(timezone.utc).strftime(
        "%d.%m.%Y %H:%M:%S UTC"
    )
    assert saved["format"] == "with_manager"
    assert saved["selection_base_minor"] == 500000
    assert saved["accompaniment_count"] == 2
    assert saved["accompaniment_minor"] == 240000
    assert saved["total_minor"] == result.total_minor == 740000
    worker = build_customer_workflow_delivery(
        env["config"], transactions, AsyncMock()
    )
    offer = await worker.offer_loader(
        dict(user_id=env["user"].user_id, order_id=result.order_id)
    )
    assert offer["saved"] and offer["selection_base_minor"] == 500000
    for locale in ("ru", "en", "kk", "be", "uz"):
        text = offer_text(offer, locale)
        assert (
            "5000 RUB" in text and "1200 RUB" in text and "777777" not in text
        )
    assert (
        await worker.offer_loader(
            dict(user_id=uuid4(), order_id=result.order_id)
        )
        is None
    )
    assert (
        await worker.offer_loader(
            dict(user_id=env["user"].user_id, order_id=uuid4())
        )
        is None
    )
    assert (
        await worker.offer_loader(dict(user_id=uuid4(), order_id=None)) is None
    )
    current = await worker.offer_loader(
        dict(user_id=env["user"].user_id, order_id=None)
    )
    assert current["selection_unit_minor"] == 50000
    for locale in ("ru", "en", "kk", "be", "uz"):
        text = offer_text(current, locale)
        assert "5000 RUB" in text and "500 RUB" in text and "1200 RUB" in text
    messenger = AsyncMock()
    delivery = env["container"].build_order_notice_delivery(messenger)
    for _ in range(100):
        if not await delivery.run_once():
            break
    messages = [
        call.kwargs["text"] for call in messenger.send_text.await_args_list
    ]
    target = [message for message in messages if "7400.00" in message]
    assert target
    target_addresses = [
        call.kwargs["chat_id"]
        for call in messenger.send_text.await_args_list
        if "7400.00" in call.kwargs["text"]
    ]
    assert len(target_addresses) == len(set(target_addresses))
    assert request.contact_reference in target[0]
    assert f"Срок подбора:</b> {due_display}" in target[0]
    assert "5000.00" in target[0] and "2400.00" in target[0]


@pytest.mark.asyncio
async def test_container_rating_and_notice_factories_use_durable_dependencies(
    intake_env,
):
    env = intake_env
    services = env["container"].build_bot_services()
    assert (
        type(services["blogger_rating_service"].eligibility_repo).__name__
        == "SqlAlchemyRatingEligibilityRepository"
    )
    assert services["order_service"].order_notices is not None
    assert services["payment_service"].order_notices is not None
    assert services["payment_repo"] is env["repos"]["payment_repo"]
    worker = env["container"].build_order_notice_delivery(AsyncMock())
    assert worker.transactions is env["container"].transaction_manager
    assert type(worker.repository).__name__ == "SqlAlchemyOrderNoticeRepository"


@pytest.mark.asyncio
async def test_real_admin_edit_renders_saved_quote_and_private_bound_image(
    intake_env, monkeypatch, tmp_path
):
    from fastapi.testclient import TestClient

    from tests.application.services.test_order_image_service import picture
    from ugc_bot.admin import app as admin_module

    env = intake_env
    monkeypatch.setenv("ORDER_IMAGE_DIRECTORY", str(tmp_path))
    images = env["container"].build_order_image_service()
    image = await images.upload(env["user"].user_id, picture())
    intake = service(env)
    intake.image_service = images
    result = await intake.create(
        command(
            env,
            position_count=10,
            service_mode="with_manager",
            accompaniment_ordinals=frozenset({1, 2}),
            contact_reference="<private-contact> & client",
            image_token=image.token,
        )
    )
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
        image_path = f"/admin/order-images/{result.order_id}"
        assert client.get(image_path).status_code == 401
        login = client.post(
            "/admin/login",
            data={"username": "admin", "password": "Strong-Image-Preview42!"},
            follow_redirects=False,
        )
        assert login.status_code == 302
        edit = client.get(f"/admin/order-model/edit/{result.order_id}")
        assert edit.status_code == 200
        assert 'id="order-saved-quote"' in edit.text
        due_display = result.selection_due_at.astimezone(timezone.utc).strftime(
            "%d.%m.%Y %H:%M:%S UTC"
        )
        assert "Согласованный срок подбора" in edit.text
        assert due_display in edit.text
        assert "&lt;private-contact&gt; &amp; client" in edit.text
        assert (
            "5000.00 RUB" in edit.text
            and "2400.00 RUB" in edit.text
            and "7400.00 RUB" in edit.text
        )
        assert image_path in edit.text
        preview = client.get(image_path)
        assert preview.status_code == 200 and preview.content == picture()
        assert preview.headers["cache-control"] == "private, no-store"
