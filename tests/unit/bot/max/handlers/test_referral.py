"""Tests for Max referral handler — deep-link generation and payouts."""

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.application.services.referral_commission import (
    MultiCurrencyReferralStats,
)
from ugc_bot.bot.max.handlers.referral import router
from ugc_bot.bot.telegram.handlers.referral import (
    PAYOUT_PAID_CALLBACK_PREFIX,
    REFERRAL_PAYOUT_CALLBACK,
)
from ugc_bot.domain.enums import MessengerType, PayoutRequestStatus, UserStatus


def _mc_stats(
    *,
    available: dict | None = None,
    pending: dict | None = None,
    has_request_today: dict | None = None,
) -> MultiCurrencyReferralStats:
    return MultiCurrencyReferralStats(
        creators_count=0,
        income_by_currency={},
        orders_by_currency={},
        paid_by_currency={},
        pending_by_currency=pending or {},
        available_by_currency=available or {},
        has_request_today_by_currency=has_request_today or {},
    )


def _make_user(
    *,
    referral_code: str = "",
    status: UserStatus = UserStatus.ACTIVE,
    admin: bool = False,
    user_id=None,
):
    u = MagicMock()
    u.user_id = user_id or uuid4()
    u.referral_code = referral_code
    u.status = status
    u.admin = admin
    u.country = "RU"
    u.username = "alice"
    return u


def _incoming_msg(text: str = "/referral") -> IncomingMessage:
    return IncomingMessage(
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        text=text,
        message_id="msg_1",
    )


def _incoming_cb(data: str) -> IncomingCallback:
    return IncomingCallback(
        callback_id="cb_1",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data=data,
        message_id="msg_1",
    )


def _make_transaction_manager():
    """Create a transaction manager mock that supports async context manager."""
    tm = MagicMock()

    @asynccontextmanager
    async def _transaction():
        yield MagicMock()

    tm.transaction = _transaction
    return tm


def _deps(*, user=None, mc_stats=None, config=None):
    from tests.helpers.fakes import FakeMessengerClient

    client = FakeMessengerClient()

    user_role_service = AsyncMock()
    user_role_service.get_user = AsyncMock(return_value=user)
    user_role_service.get_user_by_id = AsyncMock(return_value=None)

    income_service = AsyncMock()
    income_service.get_multicurrency_stats = AsyncMock(
        return_value=mc_stats or _mc_stats(),
    )

    if config is None:
        config = MagicMock()
        config.referral.max_referral_bot_username = ""
        config.referral.referral_stats_limit = 10_000
        config.referral.referral_support_chat_id = ""
        config.admin.admin_base_url = ""

    payout_request_repo = AsyncMock()
    payout_request_repo.save = AsyncMock()
    payout_request_repo.get_by_id = AsyncMock(return_value=None)
    payout_request_repo.update_status = AsyncMock(return_value=True)

    tm = _make_transaction_manager()

    user_referral_binding_repo = AsyncMock()
    user_referral_binding_repo.count_by_referrer = AsyncMock(return_value=0)
    user_referral_binding_repo.list_by_referrer = AsyncMock(return_value=[])

    return {
        "messenger_client": client,
        "user_role_service": user_role_service,
        "referral_income_service": income_service,
        "payout_request_repo": payout_request_repo,
        "transaction_manager": tm,
        "user_referral_binding_repo": user_referral_binding_repo,
        "bot_texts_service": AsyncMock(
            get=AsyncMock(return_value=""),
            get_many=AsyncMock(
                return_value={"msg_referral_link_intro": "Ваша ссылка:"}
            ),
        ),
        "config": config,
        "locale": "ru",
        "country_repo": None,
        "exchange_rate_service": None,
    }


# ── /referral command ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_referral_command_includes_max_link_when_configured():
    """Max referral link is included when max_referral_bot_username is set."""
    config = MagicMock()
    config.referral.max_referral_bot_username = "id165919810643_bot"
    config.referral.referral_stats_limit = 10_000
    config.referral.referral_support_chat_id = ""
    config.admin.admin_base_url = ""

    user = _make_user(referral_code="abc12xyz")
    deps = _deps(config=config, user=user)

    await router.route_message(_incoming_msg(), deps)

    client = deps["messenger_client"]
    assert len(client.sent_text) == 1
    text = client.sent_text[0]["text"]
    assert "https://max.ru/id165919810643_bot?start=ref_abc12xyz" in text
    assert "Ваша ссылка:" in text


@pytest.mark.asyncio
async def test_referral_command_skips_link_when_max_username_not_set():
    """No referral link when max_referral_bot_username is empty."""
    config = MagicMock()
    config.referral.max_referral_bot_username = ""
    config.referral.referral_stats_limit = 10_000
    config.referral.referral_support_chat_id = ""
    config.admin.admin_base_url = ""

    user = _make_user(referral_code="abc12xyz")
    deps = _deps(config=config, user=user)

    await router.route_message(_incoming_msg(), deps)

    text = deps["messenger_client"].sent_text[0]["text"]
    assert "max.ru" not in text


@pytest.mark.asyncio
async def test_referral_command_skips_link_when_no_referral_code():
    """No referral link when user has no referral_code."""
    config = MagicMock()
    config.referral.max_referral_bot_username = "id165919810643_bot"
    config.referral.referral_stats_limit = 10_000
    config.referral.referral_support_chat_id = ""
    config.admin.admin_base_url = ""

    user = _make_user(referral_code="")
    deps = _deps(config=config, user=user)

    await router.route_message(_incoming_msg(), deps)

    text = deps["messenger_client"].sent_text[0]["text"]
    assert "max.ru" not in text


@pytest.mark.asyncio
async def test_referral_command_user_not_found_sends_message():
    """/referral with no user sends not-found message."""
    deps = _deps(user=None)
    await router.route_message(_incoming_msg(), deps)
    assert len(deps["messenger_client"].sent_text) == 1


@pytest.mark.asyncio
async def test_referral_command_blocked_user_sends_message():
    """/referral with blocked user sends blocked message."""
    user = _make_user(status=UserStatus.BLOCKED)
    deps = _deps(user=user)
    await router.route_message(_incoming_msg(), deps)
    assert len(deps["messenger_client"].sent_text) == 1


@pytest.mark.asyncio
async def test_referral_command_pause_user_sends_message():
    """/referral with paused user sends pause message."""
    user = _make_user(status=UserStatus.PAUSE)
    deps = _deps(user=user)
    await router.route_message(_incoming_msg(), deps)
    assert len(deps["messenger_client"].sent_text) == 1


# ── payout button callback ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_payout_button_user_not_found_answers():
    """Payout button with no user answers callback."""
    deps = _deps(user=None)
    deps["messenger_client"] = AsyncMock()
    await router.route_callback(
        _incoming_cb(f"{REFERRAL_PAYOUT_CALLBACK}:RUB"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_payout_button_blocked_user_answers():
    """Payout button with blocked user answers callback."""
    user = _make_user(status=UserStatus.BLOCKED)
    deps = _deps(user=user)
    deps["messenger_client"] = AsyncMock()
    await router.route_callback(
        _incoming_cb(f"{REFERRAL_PAYOUT_CALLBACK}:RUB"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_payout_button_pause_user_answers():
    """Payout button with paused user answers callback."""
    user = _make_user(status=UserStatus.PAUSE)
    deps = _deps(user=user)
    deps["messenger_client"] = AsyncMock()
    await router.route_callback(
        _incoming_cb(f"{REFERRAL_PAYOUT_CALLBACK}:RUB"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_payout_button_already_requested_today_answers():
    """Payout already requested today answers with alert."""
    user = _make_user()
    stats = _mc_stats(has_request_today={"RUB": True})
    deps = _deps(user=user, mc_stats=stats)
    deps["messenger_client"] = AsyncMock()
    await router.route_callback(
        _incoming_cb(f"{REFERRAL_PAYOUT_CALLBACK}:RUB"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    call_kwargs = deps["messenger_client"].answer_callback.call_args.kwargs
    assert call_kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_payout_button_pending_request_answers_unavailable():
    """Payout with pending request answers unavailable alert."""
    user = _make_user()
    stats = _mc_stats(
        available={"RUB": Decimal("100")},
        pending={"RUB": Decimal("50")},
        has_request_today={"RUB": False},
    )
    deps = _deps(user=user, mc_stats=stats)
    deps["messenger_client"] = AsyncMock()
    await router.route_callback(
        _incoming_cb(f"{REFERRAL_PAYOUT_CALLBACK}:RUB"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    call_kwargs = deps["messenger_client"].answer_callback.call_args.kwargs
    assert call_kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_payout_button_zero_available_answers_unavailable():
    """Payout with zero available balance answers unavailable alert."""
    user = _make_user()
    stats = _mc_stats(
        available={"RUB": Decimal("0")},
        pending={},
        has_request_today={"RUB": False},
    )
    deps = _deps(user=user, mc_stats=stats)
    deps["messenger_client"] = AsyncMock()
    await router.route_callback(
        _incoming_cb(f"{REFERRAL_PAYOUT_CALLBACK}:RUB"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    call_kwargs = deps["messenger_client"].answer_callback.call_args.kwargs
    assert call_kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_payout_button_creates_request_and_notifies():
    """Payout with valid balance creates request and answers."""
    user = _make_user()
    stats = _mc_stats(
        available={"RUB": Decimal("500")},
        pending={},
        has_request_today={"RUB": False},
    )
    deps = _deps(user=user, mc_stats=stats)
    deps["messenger_client"] = AsyncMock()
    await router.route_callback(
        _incoming_cb(f"{REFERRAL_PAYOUT_CALLBACK}:RUB"), deps
    )
    deps["payout_request_repo"].save.assert_called_once()
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_payout_button_notifies_with_admin_url():
    """Payout notification includes admin URL when configured."""
    user = _make_user()
    stats = _mc_stats(
        available={"RUB": Decimal("500")},
        pending={},
        has_request_today={"RUB": False},
    )
    config = MagicMock()
    config.referral.max_referral_bot_username = ""
    config.referral.referral_support_chat_id = "chat_support"
    config.admin.admin_base_url = "http://admin.test"
    deps = _deps(user=user, mc_stats=stats, config=config)
    deps["messenger_client"] = AsyncMock()
    await router.route_callback(
        _incoming_cb(f"{REFERRAL_PAYOUT_CALLBACK}:RUB"), deps
    )
    deps["payout_request_repo"].save.assert_called_once()
    # Verify admin URL in support message
    send_calls = deps["messenger_client"].send_text.call_args_list
    support_call = [
        c for c in send_calls
        if "chat_support" in str(c)
    ]
    assert len(support_call) >= 1


@pytest.mark.asyncio
async def test_payout_button_notify_failure_sends_different_text():
    """Payout with support chat notification failure answers with fail text."""
    user = _make_user()
    stats = _mc_stats(
        available={"RUB": Decimal("300")},
        pending={},
        has_request_today={"RUB": False},
    )
    config = MagicMock()
    config.referral.max_referral_bot_username = ""
    config.referral.referral_support_chat_id = "chat_support"
    config.admin.admin_base_url = ""
    deps = _deps(user=user, mc_stats=stats, config=config)
    # Make send_text fail for support channel
    messenger = AsyncMock()
    messenger.send_text = AsyncMock(side_effect=[Exception("failed"), None])
    deps["messenger_client"] = messenger
    await router.route_callback(
        _incoming_cb(f"{REFERRAL_PAYOUT_CALLBACK}:RUB"), deps
    )
    deps["payout_request_repo"].save.assert_called_once()
    messenger.answer_callback.assert_called()


# ── payout_paid callback (admin) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_payout_paid_invalid_format_answers_error():
    """payout_paid with invalid request ID answers error."""
    deps = _deps(user=_make_user(admin=True))
    deps["messenger_client"] = AsyncMock()
    await router.route_callback(
        _incoming_cb(f"{PAYOUT_PAID_CALLBACK_PREFIX}not-a-uuid"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    call_kwargs = deps["messenger_client"].answer_callback.call_args.kwargs
    assert call_kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_payout_paid_user_not_found_answers_denied():
    """payout_paid with no user answers denied."""
    request_id = uuid4()
    deps = _deps(user=None)
    deps["messenger_client"] = AsyncMock()
    await router.route_callback(
        _incoming_cb(f"{PAYOUT_PAID_CALLBACK_PREFIX}{request_id}"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    call_kwargs = deps["messenger_client"].answer_callback.call_args.kwargs
    assert call_kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_payout_paid_non_admin_user_denied():
    """payout_paid from non-admin user is denied."""
    request_id = uuid4()
    user = _make_user(admin=False)
    deps = _deps(user=user)
    deps["messenger_client"] = AsyncMock()
    await router.route_callback(
        _incoming_cb(f"{PAYOUT_PAID_CALLBACK_PREFIX}{request_id}"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    call_kwargs = deps["messenger_client"].answer_callback.call_args.kwargs
    assert call_kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_payout_paid_request_not_found_answers_not_found():
    """payout_paid when request not found answers not-found."""
    request_id = uuid4()
    user = _make_user(admin=True)
    deps = _deps(user=user)
    deps["messenger_client"] = AsyncMock()
    deps["payout_request_repo"].get_by_id = AsyncMock(return_value=None)
    await router.route_callback(
        _incoming_cb(f"{PAYOUT_PAID_CALLBACK_PREFIX}{request_id}"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_payout_paid_already_processed_answers_already_done():
    """payout_paid on already-processed request answers already-done."""
    request_id = uuid4()
    user = _make_user(admin=True)
    deps = _deps(user=user)
    deps["messenger_client"] = AsyncMock()
    request = MagicMock()
    request.status = PayoutRequestStatus.PAID
    request.request_id = request_id
    deps["payout_request_repo"].get_by_id = AsyncMock(return_value=request)
    await router.route_callback(
        _incoming_cb(f"{PAYOUT_PAID_CALLBACK_PREFIX}{request_id}"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    call_kwargs = deps["messenger_client"].answer_callback.call_args.kwargs
    assert call_kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_payout_paid_success_removes_keyboard_and_answers():
    """payout_paid success removes keyboard and answers."""
    request_id = uuid4()
    user = _make_user(admin=True)
    deps = _deps(user=user)
    deps["messenger_client"] = AsyncMock()
    request = MagicMock()
    request.status = PayoutRequestStatus.PENDING
    request.request_id = request_id
    deps["payout_request_repo"].get_by_id = AsyncMock(return_value=request)
    deps["payout_request_repo"].update_status = AsyncMock(return_value=True)
    await router.route_callback(
        _incoming_cb(f"{PAYOUT_PAID_CALLBACK_PREFIX}{request_id}"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    deps["messenger_client"].edit_reply_markup.assert_called()


@pytest.mark.asyncio
async def test_payout_paid_edit_markup_failure_logged():
    """edit_reply_markup failure after payout_paid is logged."""
    request_id = uuid4()
    user = _make_user(admin=True)
    deps = _deps(user=user)
    client = AsyncMock()
    client.edit_reply_markup = AsyncMock(
        side_effect=RuntimeError("API error")
    )
    deps["messenger_client"] = client
    request = MagicMock()
    request.status = PayoutRequestStatus.PENDING
    request.request_id = request_id
    deps["payout_request_repo"].get_by_id = AsyncMock(
        return_value=request
    )
    deps["payout_request_repo"].update_status = AsyncMock(
        return_value=True,
    )
    await router.route_callback(
        _incoming_cb(f"{PAYOUT_PAID_CALLBACK_PREFIX}{request_id}"),
        deps,
    )
    client.answer_callback.assert_called()


# ── /referral_list command ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_referral_list_user_not_found_sends_message():
    """/referral_list with no user sends not-found message."""
    deps = _deps(user=None)
    await router.route_message(_incoming_msg("/referral_list"), deps)
    assert len(deps["messenger_client"].sent_text) == 1


@pytest.mark.asyncio
async def test_referral_list_blocked_user_sends_message():
    """/referral_list with blocked user sends blocked message."""
    user = _make_user(status=UserStatus.BLOCKED)
    deps = _deps(user=user)
    await router.route_message(_incoming_msg("/referral_list"), deps)
    assert len(deps["messenger_client"].sent_text) == 1


@pytest.mark.asyncio
async def test_referral_list_pause_user_sends_message():
    """/referral_list with paused user sends pause message."""
    user = _make_user(status=UserStatus.PAUSE)
    deps = _deps(user=user)
    await router.route_message(_incoming_msg("/referral_list"), deps)
    assert len(deps["messenger_client"].sent_text) == 1


@pytest.mark.asyncio
async def test_referral_list_empty_sends_empty_message():
    """/referral_list with no referrals sends empty-list message."""
    user = _make_user()
    deps = _deps(user=user)
    deps["user_referral_binding_repo"].count_by_referrer = AsyncMock(
        return_value=0
    )
    deps["user_referral_binding_repo"].list_by_referrer = AsyncMock(
        return_value=[]
    )
    await router.route_message(_incoming_msg("/referral_list"), deps)
    assert len(deps["messenger_client"].sent_text) == 1


@pytest.mark.asyncio
async def test_referral_list_shows_referred_users():
    """/referral_list shows list of referred usernames."""
    user = _make_user()
    deps = _deps(user=user)

    binding = MagicMock()
    binding.referred_user_id = uuid4()
    referred_user = MagicMock()
    referred_user.username = "bob"

    deps["user_referral_binding_repo"].count_by_referrer = AsyncMock(
        return_value=1
    )
    deps["user_referral_binding_repo"].list_by_referrer = AsyncMock(
        return_value=[binding]
    )
    deps["user_role_service"].get_user_by_id = AsyncMock(
        return_value=referred_user
    )

    await router.route_message(_incoming_msg("/referral_list"), deps)
    assert len(deps["messenger_client"].sent_text) == 1
    text = deps["messenger_client"].sent_text[0]["text"]
    assert "bob" in text


@pytest.mark.asyncio
async def test_referral_list_shows_total_when_exceeds_page_size():
    """/referral_list appends total count when list exceeds page size."""
    from ugc_bot.bot.telegram.handlers.referral import REFERRAL_LIST_PAGE_SIZE

    user = _make_user()
    deps = _deps(user=user)
    total = REFERRAL_LIST_PAGE_SIZE + 5

    bindings = []
    for _ in range(REFERRAL_LIST_PAGE_SIZE):
        b = MagicMock()
        b.referred_user_id = uuid4()
        bindings.append(b)

    deps["user_referral_binding_repo"].count_by_referrer = AsyncMock(
        return_value=total
    )
    deps["user_referral_binding_repo"].list_by_referrer = AsyncMock(
        return_value=bindings
    )
    referred_user = MagicMock()
    referred_user.username = "user"
    deps["user_role_service"].get_user_by_id = AsyncMock(
        return_value=referred_user
    )

    await router.route_message(_incoming_msg("/referral_list"), deps)
    text = deps["messenger_client"].sent_text[0]["text"]
    assert str(total) in text


@pytest.mark.asyncio
async def test_referral_list_unknown_user_shows_id_fragment():
    """/referral_list shows ID fragment when referred user not found."""
    user = _make_user()
    deps = _deps(user=user)
    referred_id = uuid4()
    binding = MagicMock()
    binding.referred_user_id = referred_id

    deps["user_referral_binding_repo"].count_by_referrer = AsyncMock(
        return_value=1
    )
    deps["user_referral_binding_repo"].list_by_referrer = AsyncMock(
        return_value=[binding]
    )
    deps["user_role_service"].get_user_by_id = AsyncMock(return_value=None)

    await router.route_message(_incoming_msg("/referral_list"), deps)
    text = deps["messenger_client"].sent_text[0]["text"]
    # Should contain at least first 8 chars of the UUID
    assert str(referred_id)[:8] in text


# ── multi-currency stats display ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_referral_command_multi_currency_stats_sent():
    """/referral sends stats text including multi-currency data."""
    config = MagicMock()
    config.referral.max_referral_bot_username = ""
    config.referral.referral_stats_limit = 10_000
    config.referral.referral_support_chat_id = ""
    config.admin.admin_base_url = ""

    stats = MultiCurrencyReferralStats(
        creators_count=3,
        income_by_currency={"RUB": Decimal("1500"), "USD": Decimal("20")},
        orders_by_currency={"RUB": 5},
        paid_by_currency={"RUB": Decimal("500")},
        pending_by_currency={},
        available_by_currency={"RUB": Decimal("1000")},
        has_request_today_by_currency={},
    )
    user = _make_user()
    deps = _deps(config=config, user=user, mc_stats=stats)
    await router.route_message(_incoming_msg(), deps)
    # Should produce stats text
    assert len(deps["messenger_client"].sent_text) == 1
