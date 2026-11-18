"""Exercise Telegram verification, admin review, and private manual contacts."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import SendMessage
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.factories import create_test_blogger_profile
from tests.helpers.fakes import FakeFSMContext, FakeMessage, FakeUser
from tests.postgres_financial.test_telegram_order_summary import (
    financial_pg_engine,
    intake_env,
    paid_order,
)
from ugc_bot.admin.app import _build_templates, _require_action_token
from ugc_bot.admin.managers import _directory, _review, register_managers
from ugc_bot.admin.order_worklist import worklist_manager_suggestions
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.ports import InstagramDirectMessage
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.bot.telegram.handlers.manager_application import (
    open_manager_application,
    review_manager_in_telegram,
    show,
)
from ugc_bot.bot.telegram.handlers.order_summary import render_card
from ugc_bot.bot.telegram.manager_review_messages import (
    REVIEW_PAGE_SIZE,
    review_queue_cursor,
    review_queue_message,
)
from ugc_bot.container.creator_invite_factory import build_creator_invites
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.domain.manager_application import (
    MANAGER_NOTICE_EVENTS,
    MANAGER_READY_FOR_REVIEW,
    MAX_WRITTEN_LENGTH,
    application_fields,
    application_version,
)
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.manager_application_models import APPLICATIONS
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    ManagerOrderModel,
    OrderItemModel,
    OutboxEventModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories import manager_applications
from ugc_bot.infrastructure.db.repositories.creator_invites import create_invite
from ugc_bot.infrastructure.db.repositories.manager_applications import (
    ManagerApplications,
)
from ugc_bot.instagram_webhook_app import _process_single_messaging_event
from ugc_bot.manager_application_delivery import ManagerApplicationDelivery
from ugc_bot.miniapp.api import router as miniapp_router
from ugc_bot.miniapp.manager_invites import InviteRequest, manager_invite_data

__all__ = ["financial_pg_engine", "intake_env"]


@pytest.mark.asyncio
@pytest.mark.parametrize("elapsed", [timedelta(minutes=22), timedelta(days=2)])
async def test_reopening_verification_keeps_the_code_already_copied_to_direct(
    intake_env, monkeypatch, caplog, elapsed
):
    env = intake_env
    user_id = env["user"].user_id
    now = datetime.now(timezone.utc).replace(microsecond=0)

    class VerificationClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(manager_applications, "datetime", VerificationClock)
    graph = SimpleNamespace(get_direct_message=AsyncMock())
    service = ManagerApplications(env["container"].transaction_manager, graph)
    await service.open(user_id)
    await service.answer(user_id, "instagram", "synthetic_manager")
    original_code = await service.instagram_challenge(user_id)
    # A challenge issued by the previous release has a fifteen-minute expiry.
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(APPLICATIONS)
            .where(APPLICATIONS.c.user_id == user_id)
            .values(challenge_until=now + timedelta(minutes=15))
        )
    now += elapsed
    with caplog.at_level("INFO", logger=manager_applications.__name__):
        assert not await service.verify_instagram_from_direct(
            original_code, "synthetic_sender", "synthetic_mid", "inbox"
        )
    graph.get_direct_message.assert_not_awaited()
    assert [r.reason for r in caplog.records if hasattr(r, "reason")] == [
        "challenge_expired"
    ]
    # Reopening must renew the same code, including codes from old messages.
    assert await service.instagram_challenge(user_id) == original_code
    renewed = await service.open(user_id)
    assert renewed["challenge_until"] == now + timedelta(hours=24)
    graph.get_direct_message.return_value = InstagramDirectMessage(
        sender_id="synthetic_sender",
        sender_username="synthetic_manager",
        recipient_usernames=("inbox",),
        text=original_code,
        created_at=now,
    )
    assert await service.verify_instagram_from_direct(
        original_code, "synthetic_sender", "synthetic_mid", "inbox"
    )
    confirmed = await service.open(user_id)
    assert confirmed["instagram_verified_at"] == now
    assert confirmed["instagram_user_id"] == "synthetic_sender"
    assert confirmed["challenge"] is None
    assert not await service.verify_instagram_from_direct(
        original_code, "synthetic_sender", "synthetic_mid", "inbox"
    )
    assert original_code not in caplog.text


@pytest.mark.asyncio
async def test_manager_challenge_stays_valid_after_fifteen_minutes(
    intake_env, monkeypatch
):
    env = intake_env
    user_id = env["user"].user_id
    now = datetime.now(timezone.utc).replace(microsecond=0)

    class VerificationClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(manager_applications, "datetime", VerificationClock)
    graph = SimpleNamespace(get_direct_message=AsyncMock())
    service = ManagerApplications(env["container"].transaction_manager, graph)
    await service.open(user_id)
    await service.answer(user_id, "instagram", "synthetic_manager")
    code = await service.instagram_challenge(user_id)
    now += timedelta(minutes=22)
    assert await service.instagram_challenge(user_id) == code
    graph.get_direct_message.return_value = InstagramDirectMessage(
        sender_id="synthetic_sender",
        sender_username="synthetic_manager",
        recipient_usernames=("inbox",),
        text=code,
        created_at=now,
    )
    assert await service.verify_instagram_from_direct(
        code, "synthetic_sender", "synthetic_mid", "inbox"
    )


@pytest.mark.asyncio
async def test_changing_instagram_invalidates_the_reusable_manager_code(
    intake_env,
):
    env = intake_env
    user_id = env["user"].user_id
    graph = SimpleNamespace(get_direct_message=AsyncMock())
    service = ManagerApplications(env["container"].transaction_manager, graph)
    await service.open(user_id)
    await service.answer(user_id, "instagram", "synthetic_manager")
    previous = await service.instagram_challenge(user_id)
    await service.answer(user_id, "instagram", "different_manager")
    current = await service.instagram_challenge(user_id)
    assert previous != current
    assert not await service.verify_instagram_from_direct(
        previous, "synthetic_sender", "synthetic_mid", "inbox"
    )
    graph.get_direct_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("temporary_candidate_failure", [False, True])
async def test_application_verification_review_and_directory(
    intake_env, monkeypatch, temporary_candidate_failure
):
    env = intake_env
    transactions = env["container"].transaction_manager
    graph = SimpleNamespace(
        get_profile_by_id=AsyncMock(
            return_value=SimpleNamespace(username="different_profile")
        ),
        get_direct_message=AsyncMock(),
    )
    delivery = ManagerApplicationDelivery(env["config"])

    async def send_verification_notices(event_ids):
        await delivery.deliver_verification_notices(transactions, event_ids)

    service = ManagerApplications(
        transactions,
        graph,
        deliver_verification_notices=send_verification_notices,
    )
    reviewers = ("kamilbakhteev", "darbulat", "usemycontent")
    reviewer_ids = [uuid4() for _ in reviewers]
    addresses = [980031, 980032, 980033]
    notification_addresses = [addresses[0], addresses[2]]
    with Session(env["pg"]) as db, db.begin():
        for reviewer, identity, address in zip(
            reviewers, reviewer_ids, addresses, strict=True
        ):
            db.add(
                UserModel(
                    user_id=identity,
                    username=reviewer,
                    telegram=reviewer,
                    telegram_id=str(address),
                    admin=True,
                    status="active",
                    messenger_type="telegram",
                )
            )
    env["config"].bot.bot_token = "123456:synthetic-review-check"
    env["config"].bot.bot_username = "synthetic_test_bot"
    env["config"].referral.referral_bot_username = "synthetic_test_bot"
    env["config"].webhook.webhook_base_url = "https://bot.example.test"
    sent: list[SendMessage] = []
    delayed_reviewer = {addresses[0]}
    delayed_confirmation = 2 if temporary_candidate_failure else 0
    delayed_ready = temporary_candidate_failure

    async def collect(_session, bot, method, timeout=None):
        assert bot.token == "123456:synthetic-review-check"
        assert isinstance(method, SendMessage)
        nonlocal delayed_confirmation, delayed_ready
        if delayed_confirmation and method.text.startswith(
            "<b>Instagram подтверждён"
        ):
            delayed_confirmation -= 1
            raise OSError("Synthetic temporary candidate delivery failure")
        if (
            delayed_ready
            and method.chat_id == notification_addresses[1]
            and "готова к проверке" in method.text
        ):
            delayed_ready = False
            raise OSError("Synthetic temporary reviewer delivery failure")
        if method.chat_id in delayed_reviewer:
            delayed_reviewer.remove(method.chat_id)
            raise OSError("Synthetic temporary Telegram outage")
        sent.append(method)

    monkeypatch.setattr(AiohttpSession, "make_request", collect)
    repos = env["container"].build_repos()
    publisher = OutboxPublisher(
        repos["outbox_repo"],
        repos["order_repo"],
        transactions,
        manager_notifier=delivery,
    )
    kafka = SimpleNamespace(publish=AsyncMock())
    miniapp = FastAPI()
    miniapp.include_router(miniapp_router, prefix="/miniapp")
    miniapp.state.config = env["config"]
    services = env["container"].build_bot_services()
    services["manager_applications"] = service
    miniapp.state.dispatcher = services
    candidate_native_id = uuid4().int % 10**12 + 1
    roles = services["user_role_service"]
    application_chat = FakeMessage(
        text="/manager", user=FakeUser(candidate_native_id, "test_manager", "")
    )
    application_chat.chat.type = "private"
    application_state = FakeFSMContext()
    await open_manager_application(
        application_chat, application_state, roles, env["config"], service
    )
    candidate = await roles.get_user(
        str(candidate_native_id), MessengerType.TELEGRAM
    )
    assert candidate is not None and not candidate.admin
    user_id = candidate.user_id

    async def manager_miniapp(path, native_id=candidate_native_id):
        async with AsyncClient(
            transport=ASGITransport(app=miniapp), base_url="http://testserver"
        ) as client:
            return await client.post(
                "/miniapp/api" + path,
                json={
                    "init_data": generate_init_data(
                        env["config"].bot.bot_token,
                        native_id,
                        "test_manager",
                    )
                },
            )

    assert (await manager_miniapp("/me")).json()["is_manager"] is False
    directory = "/manager/invited-creators"
    assert (await manager_miniapp(directory)).status_code == 403
    orders = []
    for address in addresses[:2]:
        assert (await manager_miniapp("/me", address)).json()[
            "is_manager"
        ] is True
        assert (await manager_miniapp(directory, address)).status_code == 200
        response = await manager_miniapp("/manager/orders", address)
        assert response.status_code == 200
        orders.append(response.json())
    assert orders[0] == orders[1]
    assert (await service.open(user_id))["state"] == "draft"
    answers = dict(
        name="Камиль",
        location="Казань",
        phone="+70000000000",
        instagram="@test_manager",
        case="Вёл 10 авторов для кафе. Кейс: https://cases.example.test/team\n"
        + "Согласовал съёмку и сроки, получил публикации по брифу. " * 20,
        settlement="ИП",
        rate="600–800",
        work_format="Агентство",
        weekly_capacity="11–30",
        shortfall_plan="Сверю сроки и поищу авторов в городских сообществах.",
    )
    assert set(answers) == set(application_fields(answers))
    with pytest.raises(ValueError, match="предложенных"):
        await service.answer(user_id, "weekly_capacity", "50")
    with pytest.raises(ValueError, match="две суммы"):
        await service.answer(user_id, "rate", "Обсудим")
    with pytest.raises(ValueError, match="найденного"):
        await service.answer(user_id, "location", "Казань")
    with pytest.raises(ValueError, match="Instagram"):
        await service.answer(user_id, "instagram", "@некорректный")
    for field in ("case", "shortfall_plan"):
        with pytest.raises(ValueError, match="от 20 символов"):
            await service.answer(user_id, field, "Быстро")
        with pytest.raises(
            ValueError, match=f"до {MAX_WRITTEN_LENGTH} символов"
        ):
            await service.answer(user_id, field, "я" * (MAX_WRITTEN_LENGTH + 1))
    for field, value in answers.items():
        if field in {"location", "shortfall_plan"}:
            continue
        await service.answer(user_id, field, value)
    await service.answer(
        user_id, "location", "Казань", location_context=("Татарстан", "Россия")
    )
    with pytest.raises(ValueError, match="не относится"):
        await service.answer(user_id, "work_format_details", "лишний ответ")
    await service.answer(user_id, "work_format", "Другое")
    assert (await service.open(user_id))["state"] == "draft"
    await service.answer(user_id, "work_format_details", "Веду спецпроекты")
    await service.answer(user_id, "work_format", "Агентство")
    assert "work_format_details" not in (await service.open(user_id))["answers"]
    submitted = await service.answer(
        user_id, "shortfall_plan", answers["shortfall_plan"]
    )
    assert submitted["state"] == "submitted"
    assert submitted["submitted_at"] is not None
    version = application_version(submitted["submitted_at"])
    await publisher.process_pending_events(kafka)
    assert [message.chat_id for message in sent] == notification_addresses[1:]
    await publisher.process_pending_events(kafka)
    assert sorted(message.chat_id for message in sent) == notification_addresses
    for message in sent:
        assert "Новая заявка менеджера" in message.text
        buttons = message.reply_markup.inline_keyboard
        assert buttons[0][0].url.endswith(f"/admin/managers/{user_id}")
        assert buttons[1][0].callback_data == f"mreview:v:{user_id.hex}"
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="synthetic-manager-review")
    auth = SimpleNamespace(authenticate=AsyncMock(return_value=False))
    register_managers(
        app,
        auth,
        env["pg"],
        _build_templates(app, ZoneInfo("Europe/Moscow")),
        _require_action_token,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as web:
        url = f"/admin/managers/{user_id}"
        unauthenticated = await web.get(url)
        assert unauthenticated.status_code in {302, 303, 307}
        assert unauthenticated.headers["location"].startswith("/admin/login")
        auth.authenticate.return_value = True
        assert (await web.get(f"/admin/managers/{uuid4()}")).status_code == 404
        queue = await web.get("/admin/managers", params={"status": "submitted"})
        assert queue.status_code == 200 and url in queue.text
        card = await web.get(url)
        assert (
            card.status_code == 200
            and card.headers["cache-control"] == "no-store"
        )
        assert (
            "Контакты и география" in card.text
            and "Условия работы" in card.text
        )
        assert "600–800 ₽" in card.text and "Россия" in card.text
        assert answers["shortfall_plan"] in card.text
        assert 'value="approved" disabled' in card.text
        assert 'name="csrf_token"' in card.text
        assert "Внутренняя заметка" in card.text
        assert 'href="https://cases.example.test/team"' in card.text
        assert answers["case"].rsplit("\n", 1)[1].strip() in card.text

    reviewer = SimpleNamespace(
        user_id=reviewer_ids[0], admin=True, status=UserStatus.ACTIVE
    )
    users = SimpleNamespace(get_user=AsyncMock(return_value=reviewer))
    messenger = SimpleNamespace(send_text=AsyncMock())

    async def click_review(data, *, chat_type="private", reviewer_index=0):
        address = addresses[reviewer_index]
        callback = SimpleNamespace(
            message=SimpleNamespace(
                chat=SimpleNamespace(id=address, type=chat_type)
            ),
            from_user=SimpleNamespace(id=address),
            data=data,
            answer=AsyncMock(),
        )
        await review_manager_in_telegram(
            callback, users, env["config"], messenger, service
        )
        return callback.answer

    open_button = f"mreview:v:{user_id.hex}"
    response = await click_review(open_button, chat_type="group")
    response.assert_awaited_once_with()
    users.get_user.assert_not_awaited()
    reviewer.admin = False
    response = await click_review(open_button)
    assert "администраторам" in response.call_args.args[0]
    assert response.call_args.kwargs["show_alert"]
    response = await click_review("mreview:q")
    assert "администраторам" in response.call_args.args[0]
    messenger.send_text.assert_not_awaited()
    reviewer.admin = True
    response = await click_review("mreview:v:bad-id")
    assert "недействительна" in response.call_args.args[0]
    response = await click_review(f"mreview:v:{uuid4().hex}")
    assert "не найдена" in response.call_args.args[0]
    messenger.send_text.assert_not_awaited()
    await click_review("mreview:q")
    result = messenger.send_text.call_args.kwargs
    assert "нет заявок" in result["text"] and result["keyboard"] is None
    response = await click_review("mreview:q:invalid")
    response.assert_awaited_once_with(
        "Откройте список заявок заново.", show_alert=True
    )

    await click_review(open_button)
    displayed = messenger.send_text.call_args.kwargs
    assert displayed["chat_id"] == str(addresses[0])
    assert "<b>Город</b> · Казань" in displayed["text"]
    assert "<blockquote>Вёл 10 авторов для кафе." in displayed["text"]
    assert "Полные ответы открываются в админке." in displayed["text"]
    assert all(
        button.callback_data is None
        or not button.callback_data.startswith("mreview:a:")
        for row in displayed["keyboard"].rows
        for button in row
    )
    response = await click_review(f"mreview:a:{user_id.hex}:{version}")
    assert "Instagram" in response.call_args.args[0]
    with pytest.raises(ValueError, match="уже на рассмотрении"):
        await service.answer(
            user_id, "shortfall_plan", answers["shortfall_plan"]
        )
    with Session(env["pg"]) as db, db.begin():
        with pytest.raises(ValueError, match="Instagram"):
            _review(db, "approved", str(user_id), "")
        _review(db, "clarify", str(user_id), "Уточните загрузку")
    internal = await service.open(user_id)
    assert internal["decision_note"] == "Уточните загрузку"
    candidate_chat = SimpleNamespace(answer=AsyncMock())
    await show(candidate_chat, internal, env["config"])
    assert "на рассмотрении" in candidate_chat.answer.call_args.args[0]
    assert "Уточните загрузку" not in candidate_chat.answer.call_args.args[0]
    await service.answer(user_id, "coverage", "Казань, 10 авторов")
    await service.answer(user_id, "shortfall_plan", answers["shortfall_plan"])
    code = await service.instagram_challenge(user_id)
    assert code == await service.instagram_challenge(user_id)
    assert not await service.verify_instagram(code, "synthetic_instagram_id")
    env["config"].instagram.admin_instagram_username = "@expected_inbox"
    proof = InstagramDirectMessage(
        sender_id="synthetic_instagram_id",
        sender_username="test_manager",
        recipient_usernames=("expected_inbox",),
        text=code,
        created_at=datetime.now(timezone.utc).replace(microsecond=0),
    )
    request = (code, proof.sender_id, "meta-message-id", "@expected_inbox")
    assert not await service.verify_instagram_from_direct(
        *request[:2], "", request[3]
    )
    assert not await service.verify_instagram_from_direct(
        "UMCM-000000000000", *request[1:]
    )
    graph.get_direct_message.assert_not_awaited()
    for bad_proof in (
        None,
        replace(proof, sender_id="different_sender"),
        replace(proof, sender_username="different_handle"),
        replace(proof, recipient_usernames=("some_other_inbox",)),
        replace(proof, text="A different message"),
        replace(proof, created_at=proof.created_at - timedelta(minutes=30)),
    ):
        graph.get_direct_message.return_value = bad_proof
        assert not await service.verify_instagram_from_direct(*request)
    graph.get_direct_message.return_value = proof
    webhook_event = {
        "sender": {"id": "synthetic_instagram_id"},
        "message": {"text": code, "mid": "meta-message-id"},
    }
    creator_verifier = SimpleNamespace(
        verify_code_by_instagram_sender=AsyncMock()
    )
    for _ in range(2):
        assert await _process_single_messaging_event(
            webhook_event,
            creator_verifier,
            env["config"],
            service,
            manager_signature_verified=False,
        )
    creator_verifier.verify_code_by_instagram_sender.assert_not_awaited()
    immediate_confirmations = [
        m for m in sent if m.text.startswith("<b>Instagram подтверждён ✅")
    ]
    assert len(immediate_confirmations) == int(not temporary_candidate_failure)
    assert (await manager_miniapp(directory)).status_code == 403
    if temporary_candidate_failure:
        assert [m.chat_id for m in sent if "готова к проверке" in m.text] == [
            addresses[0]
        ]
        await publisher.process_pending_events(kafka)
    ready = [m for m in sent if "готова к проверке" in m.text]
    assert sorted(m.chat_id for m in ready) == notification_addresses
    ready_actions = [m.reply_markup.inline_keyboard[0][0] for m in ready]
    assert all(a.text == "Принять менеджера" for a in ready_actions)
    assert ready_actions[0].callback_data == ready_actions[1].callback_data
    approve_from_notice = ready_actions[0]

    submitted = await service.review_card(user_id)
    legacy_event_id = uuid4()
    with Session(env["pg"]) as db, db.begin():
        db.add(
            OutboxEventModel(
                event_id=legacy_event_id,
                aggregate_id=str(user_id),
                aggregate_type="manager_application",
                event_type=MANAGER_READY_FOR_REVIEW,
                created_at=datetime.now(timezone.utc),
                payload={
                    "submission": application_version(submitted["submitted_at"])
                },
            )
        )
    await delivery.deliver_verification_notices(transactions, [legacy_event_id])
    assert sent[-1].chat_id == addresses[0]
    assert sent[-1].reply_markup.inline_keyboard[0][0] == approve_from_notice
    with pytest.raises(ValueError, match="обновилась"):
        await service.approve_in_telegram(user_id, reviewer_ids[0], version)
    with pytest.raises(ValueError, match="администраторам"):
        await service.approve_in_telegram(
            user_id,
            env["user"].user_id,
            application_version(submitted["submitted_at"]),
        )
    await click_review(open_button)
    approval = messenger.send_text.call_args.kwargs["keyboard"].rows[0][0]
    assert approval.text == "Принять менеджера"
    assert len(approval.callback_data.encode()) <= 64
    assert approval.callback_data == approve_from_notice.callback_data
    with Session(env["pg"]) as db, db.begin():
        _review(db, "note", str(user_id), "Внутренний комментарий")
        _review(db, "clarify", str(user_id), "")
    assert (await service.review_card(user_id))["state"] == "clarify"
    users.get_user.side_effect = roles.get_user
    for index in (0, 1):
        response = await click_review("mreview:q", reviewer_index=index)
        response.assert_awaited_once_with()
        queue = messenger.send_text.call_args.kwargs
        assert queue["chat_id"] == str(addresses[index])
        assert queue["keyboard"].rows[0][0].callback_data == open_button
        await click_review(open_button, reviewer_index=index)
        card = messenger.send_text.call_args.kwargs
        assert (
            card["keyboard"].rows[0][0].callback_data == approval.callback_data
        )
    approver_index = int(temporary_candidate_failure)
    response = await click_review(
        approve_from_notice.callback_data, reviewer_index=approver_index
    )
    response.assert_awaited_once_with("Менеджер принят.")
    assert "Одобрен" in messenger.send_text.call_args.kwargs["text"]
    response = await click_review(
        approval.callback_data, reviewer_index=1 - approver_index
    )
    assert response.call_args.kwargs["show_alert"]
    assert "уже обработана" in response.call_args.args[0]
    await click_review("mreview:q", reviewer_index=approver_index)
    assert messenger.send_text.call_args.kwargs["keyboard"] is None
    with Session(env["pg"]) as db, db.begin():
        manager = db.get(UserModel, user_id)
        manager.telegram = "test_manager"
        with pytest.raises(ValueError, match="уже обработана"):
            _review(db, "approved", str(user_id), "")
        assert "test_manager" in worklist_manager_suggestions(db)
        rows = _directory(db, "Казань", "available", 0)
        assert [r["user_id"] for r in rows] == [user_id]
        country_rows = _directory(db, "Россия", "available", 0)
        assert [r["user_id"] for r in country_rows] == [user_id]
        assert rows[0]["answers"]["weekly_capacity"] == "11–30"
        assert rows[0]["answers"]["work_format"] == "Агентство"
        assert rows[0]["answers"]["location"] == "Казань"
        assert rows[0]["answers"]["location_region"] == "Татарстан"
        assert rows[0]["answers"]["location_country"] == "Россия"
    assert await service.approved(user_id)
    await publisher.process_pending_events(kafka)
    await publisher.process_pending_events(kafka)
    kafka.publish.assert_not_called()
    (confirmation,) = [
        m for m in sent if m.text.startswith("<b>Instagram подтверждён ✅")
    ]
    assert confirmation.chat_id == candidate_native_id
    expected = (
        "Анкета одобрена"
        if temporary_candidate_failure
        else "Анкета передана команде"
    )
    assert expected in confirmation.text
    if temporary_candidate_failure:
        assert confirmation.reply_markup.inline_keyboard[0][
            0
        ].web_app.url.endswith("?view=manager&section=creators")
    else:
        assert "/manager" in confirmation.text
        assert (
            confirmation.reply_markup.inline_keyboard[0][0].callback_data
            == "mgr:status"
        )
    alerts = [message for message in sent if "Новая заявка" in message.text]
    assert sorted(message.chat_id for message in alerts) == sorted(
        notification_addresses * 2
    )
    (welcome,) = [message for message in sent if "Вы приняты" in message.text]
    assert welcome.chat_id == candidate_native_id
    assert "Пополняйте свою базу блогеров" in welcome.text
    assert "С сегодняшнего дня можете начинать работу" in welcome.text
    assert "Внутренний комментарий" not in welcome.text
    assert (await service.review_card(user_id))["decision_note"] == (
        "Внутренний комментарий"
    )
    buttons = welcome.reply_markup.inline_keyboard
    directory_url = buttons[0][0].web_app.url
    assert directory_url.endswith("?view=manager&section=creators")
    assert buttons[1][0].web_app.url.endswith("?view=manager")
    assert buttons[2][0].web_app.url.endswith("?view=partner")
    assert buttons[3][0].url == "https://usemycontent.ru/partner"
    await open_manager_application(
        application_chat, application_state, roles, env["config"], service
    )
    _, reopened = application_chat.answers[-1]
    assert reopened.inline_keyboard[0][0].web_app.url == directory_url
    assert (await manager_miniapp("/me")).json()["is_manager"] is True
    assert (await manager_miniapp(directory)).json()["creators"] == []
    partner = await manager_miniapp("/partner/view")
    assert partner.json()["referral"]["link"].endswith(
        f"?start=ref_{candidate.referral_code}"
    )
    creator = await roles.set_user(
        str(uuid4().int % 10**12 + 1), MessengerType.TELEGRAM, "New creator"
    )
    assert await services["referral_service"].save_pending_referral(
        creator.user_id, candidate.referral_code
    )
    await create_test_blogger_profile(
        repos["blogger_repo"], creator.user_id, agreement_confirmed_at=None
    )
    await services["blogger_registration_service"].confirm_blogger_agreement(
        creator.user_id
    )
    listing = await manager_miniapp(directory)
    assert listing.status_code == 200
    assert [row["creator_id"] for row in listing.json()["creators"]] == [
        str(creator.user_id)
    ]
    with Session(env["pg"]) as db:
        events = db.scalars(
            select(OutboxEventModel).where(
                OutboxEventModel.event_type.in_(MANAGER_NOTICE_EVENTS)
            )
        ).all()
        assert len(events) == 9 and all(
            event.status == "published" for event in events
        )


@pytest.mark.asyncio
async def test_review_queue_next_keeps_unseen_applications_after_approvals(
    intake_env,
):
    env = intake_env
    service = ManagerApplications(env["container"].transaction_manager, None)
    queued_at = datetime.now(timezone.utc)
    identities = sorted(uuid4() for _ in range(REVIEW_PAGE_SIZE + 1))
    with Session(env["pg"]) as db, db.begin():
        db.add_all(
            UserModel(
                user_id=identity,
                username="Candidate",
                status=UserStatus.ACTIVE,
                messenger_type=MessengerType.TELEGRAM,
            )
            for identity in identities
        )
        db.flush()
        db.execute(
            APPLICATIONS.insert(),
            [
                {
                    "user_id": identity,
                    "state": "submitted",
                    "answers": {},
                    "updated_at": queued_at,
                    "submitted_at": queued_at,
                    "instagram_verified_at": queued_at,
                }
                for identity in identities
            ],
        )

    first = await service.review_queue(after=None, limit=REVIEW_PAGE_SIZE + 1)
    _, markup = review_queue_message(first, after=None)
    next_page = markup.rows[-1][0].callback_data
    after = review_queue_cursor(next_page.removeprefix("mreview:q:"))
    for identity in (identities[0], identities[REVIEW_PAGE_SIZE - 1]):
        await service.approve_in_telegram(
            identity, env["admin"].user_id, application_version(queued_at)
        )

    second = await service.review_queue(after=after, limit=REVIEW_PAGE_SIZE + 1)
    assert [row["user_id"] for row in second] == identities[REVIEW_PAGE_SIZE:]


@pytest.mark.asyncio
async def test_staff_contact_for_own_order_and_manager_notice(intake_env):
    env = intake_env
    order_summary, order_id, _, client, bot = await paid_order(
        env, interested_creators=0
    )
    service = build_creator_invites(order_summary.transactions)
    clock = env["clock"]
    service.clock = service.selection.clock = service.delivery.clock = clock
    manager = env["admin"]
    with Session(env["pg"]) as db, db.begin():
        position = db.scalar(
            select(OrderItemModel).where(
                OrderItemModel.order_id == order_id, OrderItemModel.ordinal == 1
            )
        )
        item = position.paid_item_id
        db.add(
            ManagerOrderModel(
                order_id=order_id,
                user_id=manager.user_id,
                created_at=clock.now(),
            )
        )
    body = InviteRequest(
        init_data="synthetic",
        item_id=item,
        instagram="@from_direct",
        telegram="@direct_creator",
        consent_source="instagram",
        name="Мурат",
    )
    with pytest.raises(PermissionError):
        manager_invite_data(
            env["pg"], client.user_id, order_id, body, "test_bot"
        )
    response = manager_invite_data(
        env["pg"], manager.user_id, order_id, body, "test_bot"
    )
    invite = response["invites"][0]
    identity = invite["id"]
    assert invite["expires_at"] - invite["reported_at"] == timedelta(days=30)
    data = await order_summary.view(client, order_id)
    _, keyboard = render_card(order_summary, data)
    assert any(
        "staff:" in b.callback_data for row in keyboard.rows for b in row
    )
    assert "@direct_creator" in await service.reported_contact_text(
        client, identity
    )
    outsider = AuthenticatedMessengerPrincipal(
        manager.user_id, "telegram", manager.telegram_id
    )
    with pytest.raises(ValueError, match="unavailable"):
        await service.reported_contact_text(outsider, identity)
    assert not (await order_summary.view(client, order_id))["positions"][0][
        "contact_delivered"
    ]
    with pytest.raises(ValueError, match="unavailable"):
        await service.acknowledge_staff_contact(outsider, identity)
    await service.acknowledge_staff_contact(client, identity)
    await service.acknowledge_staff_contact(client, identity)
    staff_at = clock.now()
    assert (await order_summary.view(client, order_id))["positions"][0][
        "contact_at"
    ] == staff_at
    async with service.transactions.transaction() as session:
        snapshot = await order_summary.maturity.repository.load(
            order_id, session=session
        )
        assert snapshot.positions[0].delivery_id == identity
    assert await service.claim_manager_notice(identity) is None
    assert await service.delivery.run_once() == 0
    bot.send_message.assert_not_awaited()

    with Session(env["pg"]) as db, db.begin():
        with pytest.raises(ValueError, match="position_unavailable"):
            create_invite(
                db,
                order_id,
                item,
                manager.user_id,
                "@another_creator",
                clock.now(),
                telegram="@another_creator",
                consent_source="telegram",
            )
        row = (
            db.execute(select(INVITES).where(INVITES.c.id == identity))
            .mappings()
            .one()
        )
        assert row["reported_by"] == str(manager.user_id)
        assert row["consent_source"] == "instagram"
        from tests.postgres_financial.test_creator_social import seed_profile

        creator = seed_profile(db, stable_id=uuid4().hex)
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == creator)
            .values(status="active", telegram="direct_creator")
        )
        db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == creator)
            .values(instagram_url="https://instagram.com/from_direct")
        )
    clock.at += timedelta(minutes=1)
    with pytest.raises(ValueError, match="use_personal_link"):
        await service.selection.respond(order_id, creator)
    accepted = await service.accept(identity, creator)
    assert accepted.paid_item_id == item
    from tests.postgres_financial.test_creator_invites import fake_receipt

    contact_transport = SimpleNamespace(
        send=AsyncMock(side_effect=fake_receipt)
    )
    await service.card_contact(
        client, accepted.assignment_id, contact_transport
    )
    async with service.transactions.transaction() as session:
        snapshot = await order_summary.maturity.repository.load(
            order_id, session=session
        )
        assert snapshot.positions[0].delivery_id == identity
        assert snapshot.positions[0].delivered_at == staff_at
    assert (await order_summary.view(client, order_id))["positions"][0][
        "contact_at"
    ] == staff_at

    assert await service.claim_manager_notice(identity) == (
        int(manager.telegram_id),
        order_id,
        1,
    )
    assert await service.claim_manager_notice(identity) is None
    with pytest.raises(ValueError, match="unavailable"):
        await service.reported_contact_text(client, identity)
    assert await service.delivery.run_once() == 0
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_register_known_manager_with_existing_draft(intake_env):
    env = intake_env
    uid = env["admin"].user_id
    service = ManagerApplications(env["container"].transaction_manager, None)
    await service.open(uid)
    await service.answer(uid, "name", "Менеджер")
    with Session(env["pg"]) as db, db.begin():
        db.get(UserModel, uid).telegram = "known_manager"
        _review(db, "register", "@known_manager", "")
    row = await service.open(uid)
    assert row["registered_by_admin"]
    assert row["answers"]["name"] == "Менеджер"
    assert row["instagram_verified_at"] is None
    assert await service.approved(uid)
