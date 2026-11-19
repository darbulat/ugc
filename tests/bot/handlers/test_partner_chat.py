"""The chat and Mini App show the same own-only referral account and terms."""

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.helpers.factories import create_test_user
from tests.helpers.fakes import FakeMessengerClient
from ugc_bot.application.messenger.dto import IncomingMessage, IncomingUser
from ugc_bot.application.partner_view_ports import PartnerReadFacts
from ugc_bot.application.services.partner_view_service import PartnerViewService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.partner_entry import send_telegram_partner_entry
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.messenger.telegram.client import (
    build_keyboard_markup,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", DEFAULT_TEXTS)
@pytest.mark.parametrize("app_available", [True, False])
async def test_partner_can_start_in_chat_without_a_role_profile(
    user_repo,
    fake_tm,
    config,
    bot_texts_service,
    locale,
    app_available,
):
    users = UserRoleService(user_repo=user_repo)
    reads = []

    async def read(actor_id, at, **kwargs):
        user = await user_repo.get_by_id(actor_id)
        reads.append((actor_id, kwargs))
        return PartnerReadFacts(
            actor_id,
            "active",
            user.referral_code,
            105,
            0,
            (),
            None,
            None,
            None,
            None,
        )

    view_service = PartnerViewService(
        SimpleNamespace(read=read),
        SimpleNamespace(now=lambda: datetime.now(timezone.utc)),
        {"telegram": "synthetic_bot"},
    )
    config.webhook.webhook_base_url = (
        "https://bot.example.test" if app_available else ""
    )
    incoming = IncomingMessage(
        "777", IncomingUser("777", MessengerType.TELEGRAM)
    )
    client = FakeMessengerClient()
    for _ in range(2):
        await send_telegram_partner_entry(
            incoming,
            client,
            config,
            locale,
            users,
            view_service,
            fake_tm,
            bot_texts_service,
        )
    user = await users.get_user("777", MessengerType.TELEGRAM)
    assert len({actor_id for actor_id, _ in reads}) == 1
    assert reads[0][1]["principal"].user_id == user.user_id
    assert reads[0][1]["principal"].external_id == "777"
    miniapp = await view_service.view(
        user.user_id,
        platform="telegram",
        writes_paused=True,
        session=object(),
    )
    request = client.sent_text[-1]
    assert miniapp["referral"]["link"] in request["text"]
    assert "12%" in request["text"] and "105" in request["text"]
    assert "20%" in request["text"] and "3%" in request["text"]
    markup = build_keyboard_markup(request["keyboard"])
    copy = markup.inline_keyboard[0][0]
    assert copy.copy_text.text == miniapp["referral"]["link"]
    assert copy.text == DEFAULT_TEXTS[locale]["btn_copy_referral_link"]
    assert markup.inline_keyboard[-1][0].callback_data == "nav:home"
    assert (
        any(b.web_app for row in markup.inline_keyboard for b in row)
        == app_available
    )
    assert (
        client.sent_text[0]["keyboard"].rows[0][0].copy_text
        == copy.copy_text.text
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_chat", [True, False])
async def test_partner_rejects_group_and_blocked_account(
    user_repo,
    fake_tm,
    config,
    foreign_chat,
):
    user = await create_test_user(user_repo, external_id="777")
    await user_repo.save(replace(user, status=UserStatus.BLOCKED))
    client = FakeMessengerClient()
    service = SimpleNamespace(view=AsyncMock())
    incoming = IncomingMessage(
        "-100" if foreign_chat else "777",
        IncomingUser("777", MessengerType.TELEGRAM),
    )
    await send_telegram_partner_entry(
        incoming,
        client,
        config,
        "ru",
        UserRoleService(user_repo=user_repo),
        service,
        fake_tm,
    )
    service.view.assert_not_awaited()
    if foreign_chat:
        assert client.sent_text == []
    else:
        assert not any(
            b.copy_text
            for row in client.sent_text[0]["keyboard"].rows
            for b in row
        )


@pytest.mark.asyncio
async def test_missing_link_or_backend_never_fabricates_a_personal_link(
    user_repo,
    fake_tm,
    config,
):
    user = await create_test_user(user_repo, external_id="777")
    client = FakeMessengerClient()
    service = SimpleNamespace(
        view=AsyncMock(side_effect=ConnectionError("private"))
    )
    incoming = IncomingMessage(
        "777", IncomingUser("777", MessengerType.TELEGRAM)
    )
    await send_telegram_partner_entry(
        incoming,
        client,
        config,
        "ru",
        UserRoleService(user_repo=user_repo),
        service,
        fake_tm,
    )
    assert str(user.user_id) not in client.sent_text[0]["text"]
    assert "private" not in client.sent_text[0]["text"]
    assert not any(
        b.copy_text for row in client.sent_text[0]["keyboard"].rows for b in row
    )
    assert (
        client.sent_text[0]["keyboard"].rows[-1][0].callback_data == "nav:home"
    )


@pytest.mark.asyncio
async def test_unconfigured_referral_username_still_shows_terms_without_copy(
    user_repo,
    fake_tm,
    config,
):
    user = await create_test_user(user_repo, external_id="777")

    async def read(actor_id, at, **kwargs):
        return PartnerReadFacts(
            actor_id,
            "active",
            user.referral_code,
            0,
            0,
            (),
            None,
            None,
            None,
            None,
        )

    service = PartnerViewService(
        SimpleNamespace(read=read),
        SimpleNamespace(now=lambda: datetime.now(timezone.utc)),
        {},
    )
    client = FakeMessengerClient()
    await send_telegram_partner_entry(
        IncomingMessage("777", IncomingUser("777", MessengerType.TELEGRAM)),
        client,
        config,
        "ru",
        UserRoleService(user_repo=user_repo),
        service,
        fake_tm,
    )
    assert "10%" in client.sent_text[0]["text"]
    assert (
        DEFAULT_TEXTS["ru"]["msg_partner_link_unavailable"]
        in client.sent_text[0]["text"]
    )
    assert not any(
        b.copy_text for row in client.sent_text[0]["keyboard"].rows for b in row
    )
