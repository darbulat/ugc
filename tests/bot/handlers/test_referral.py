"""Tests for referral handlers: /referral, payout, /referral_list."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers.fakes import FakeCallback, FakeMessage, FakeUser
from ugc_bot.application.services.referral_income_service import (
    ReferralIncomeService,
    UserReferralStats,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.referral import (
    REFERRAL_LIST_CALLBACK_PREFIX,
    REFERRAL_PAYOUT_CALLBACK,
    payout_button_callback,
    referral_command,
    referral_list_command,
    referral_list_pagination_callback,
)
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryUserReferralBindingRepository,
    InMemoryUserReferralPendingRepository,
    InMemoryUserRepository,
)


@pytest.mark.asyncio
async def test_referral_command_sends_stats_and_keyboard(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """referral_command sends referral stats and payout keyboard."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(
        __user(
            external_id="123",
            username="alice",
        )
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=UserReferralStats(
            creators_count=0,
            orders_count=0,
            income_current_month=0.0,
            income_total=0.0,
            paid_total=0.0,
            has_pending_payout=False,
            has_request_today=False,
        )
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(text="/referral", user=FakeUser(123, "u", "alice"))

    await referral_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(referral_stats_limit=10_000),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    text = client.sent_text[0]["text"]
    assert (
        "Реферальная статистика" in text
        or "Referral" in text
        or "статистика" in text
    )
    assert (
        "Приведено креаторов: 0" in text
        or "Creators referred: 0" in text
        or "0" in text
    )
    assert (
        "Выплачено: 0.00" in text or "Paid out: 0.00" in text or "0.00" in text
    )
    assert (
        "Текущий баланс: 0.00" in text
        or "Current balance: 0.00" in text
        or "0.00" in text
    )
    # No payout button when balance is zero
    assert client.sent_text[0]["keyboard"] is None


@pytest.mark.asyncio
async def test_referral_command_includes_link_when_bot_username_and_code_set(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """When bot_username and referral_code set, message includes link."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(
        __user(
            external_id="456",
            username="bob",
            referral_code="abc12xyz",
        )
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=UserReferralStats(
            creators_count=0,
            orders_count=0,
            income_current_month=0.0,
            income_total=0.0,
            paid_total=0.0,
            has_pending_payout=False,
            has_request_today=False,
        )
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(text="/referral", user=FakeUser(456, "u", "bob"))

    await referral_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(
                referral_stats_limit=10_000,
                referral_bot_username="MyBot",
            ),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    text = client.sent_text[0]["text"]
    assert "Ваша реферальная ссылка" in text or "referral link" in text.lower()
    assert "https://t.me/MyBot?start=ref_abc12xyz" in text


@pytest.mark.asyncio
async def test_referral_command_shows_payout_button_when_balance_positive(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """referral_command shows payout keyboard when income_total > 0."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(
        __user(external_id="456", username="bob"),
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=UserReferralStats(
            creators_count=1,
            orders_count=2,
            income_current_month=100.0,
            income_total=500.0,
            paid_total=0.0,
            has_pending_payout=False,
            has_request_today=False,
        )
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(text="/referral", user=FakeUser(456, "u", "bob"))

    await referral_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(referral_stats_limit=10_000),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    text = client.sent_text[0]["text"]
    assert "500.00" in text
    assert client.sent_text[0]["keyboard"] is not None


@pytest.mark.asyncio
async def test_referral_command_hides_payout_button_when_pending_request(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """referral_command hides payout when has_pending_payout is True."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(
        __user(external_id="789", username="carol"),
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=UserReferralStats(
            creators_count=0,
            orders_count=0,
            income_current_month=0.0,
            income_total=100.0,
            paid_total=0.0,
            has_pending_payout=True,
            has_request_today=False,
        )
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(text="/referral", user=FakeUser(789, "u", "carol"))

    await referral_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(referral_stats_limit=10_000),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    assert "100.00" in client.sent_text[0]["text"]
    assert client.sent_text[0]["keyboard"] is None


@pytest.mark.asyncio
async def test_referral_command_hides_payout_button_when_request_today(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """referral_command hides payout keyboard when has_request_today is True."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(
        __user(external_id="111", username="u1"),
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=UserReferralStats(
            creators_count=0,
            orders_count=0,
            income_current_month=0.0,
            income_total=100.0,
            paid_total=0.0,
            has_pending_payout=False,
            has_request_today=True,
        )
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(text="/referral", user=FakeUser(111, "u", "u1"))

    await referral_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(referral_stats_limit=10_000),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    assert "100.00" in client.sent_text[0]["text"]
    assert client.sent_text[0]["keyboard"] is None


@pytest.mark.asyncio
async def test_payout_button_callback_creates_request_and_answers(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """payout_button_callback creates PayoutRequest and answers callback."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(
        __user(external_id="456", username="bob"),
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=UserReferralStats(
            creators_count=0,
            orders_count=0,
            income_current_month=0.0,
            income_total=300.50,
            paid_total=0.0,
            has_pending_payout=False,
            has_request_today=False,
        )
    )
    mock_payout_repo = MagicMock()
    mock_payout_repo.save = AsyncMock(return_value=None)
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()

    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=REFERRAL_PAYOUT_CALLBACK,
        user=FakeUser(456, "u", "bob"),
        callback_id="cb1",
    )

    await payout_button_callback(
        callback,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        payout_request_repo=mock_payout_repo,
        transaction_manager=mock_tm,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(
                referral_support_chat_id="",
                referral_stats_limit=10_000,
            ),
            admin=MagicMock(admin_base_url=""),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert mock_payout_repo.save.called
    assert any(
        "Запрос на выплату отправлен" in a.get("text", "")
        for a in client.answered_callbacks
    )


@pytest.mark.asyncio
async def test_payout_button_callback_user_not_found_returns_early(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """When user not in DB, payout callback returns without creating request."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_payout_repo = MagicMock()
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=REFERRAL_PAYOUT_CALLBACK,
        user=FakeUser(99999, "u", "nonexistent"),
        callback_id="cb_none",
    )
    await payout_button_callback(
        callback,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        payout_request_repo=mock_payout_repo,
        transaction_manager=mock_tm,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(
                referral_support_chat_id="",
                referral_stats_limit=10_000,
            ),
            admin=MagicMock(admin_base_url=""),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    mock_payout_repo.save.assert_not_called()


@pytest.mark.asyncio
async def test_payout_callback_integrity_error_shows_already_requested(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """On IntegrityError (duplicate same day), show already-requested msg."""
    from sqlalchemy.exc import IntegrityError

    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(__user(external_id="777", username="u7"))
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=UserReferralStats(
            creators_count=0,
            orders_count=0,
            income_current_month=0.0,
            income_total=50.0,
            paid_total=0.0,
            has_pending_payout=False,
            has_request_today=False,
        )
    )
    mock_payout_repo = MagicMock()
    mock_payout_repo.save = AsyncMock(
        side_effect=IntegrityError("duplicate key", None, None)
    )
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()

    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=REFERRAL_PAYOUT_CALLBACK,
        user=FakeUser(777, "u", "u7"),
        callback_id="cb_dup",
    )

    await payout_button_callback(
        callback,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        payout_request_repo=mock_payout_repo,
        transaction_manager=mock_tm,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(
                referral_support_chat_id="",
                referral_stats_limit=10_000,
            ),
            admin=MagicMock(admin_base_url=""),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any(
        "подавали заявку на вывод сегодня" in a.get("text", "")
        for a in client.answered_callbacks
    )


@pytest.mark.asyncio
async def test_payout_callback_includes_admin_link_when_base_url_set(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """When admin_base_url is set, support message contains admin edit link."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(
        __user(external_id="888", username="u8"),
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=UserReferralStats(
            creators_count=0,
            orders_count=0,
            income_current_month=0.0,
            income_total=200.0,
            paid_total=0.0,
            has_pending_payout=False,
            has_request_today=False,
        )
    )
    mock_payout_repo = MagicMock()
    mock_payout_repo.save = AsyncMock(return_value=None)
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()

    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=REFERRAL_PAYOUT_CALLBACK,
        user=FakeUser(888, "u", "u8"),
        callback_id="cb_admin",
    )

    await payout_button_callback(
        callback,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        payout_request_repo=mock_payout_repo,
        transaction_manager=mock_tm,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(
                referral_support_chat_id="support_chat",
                referral_stats_limit=10_000,
            ),
            admin=MagicMock(admin_base_url="https://admin.example.com/admin"),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    assert client.sent_text[0]["chat_id"] == "support_chat"
    assert "Открыть в админке" in client.sent_text[0]["text"]
    assert "payout-request-model/edit/" in client.sent_text[0]["text"]


@pytest.mark.asyncio
async def test_payout_callback_rejects_when_request_already_today(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """payout_button_callback does not create request if has_request_today."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(__user(external_id="222", username="u2"))
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=UserReferralStats(
            creators_count=0,
            orders_count=0,
            income_current_month=0.0,
            income_total=50.0,
            paid_total=0.0,
            has_pending_payout=False,
            has_request_today=True,
        )
    )
    mock_payout_repo = MagicMock()
    mock_payout_repo.save = AsyncMock(return_value=None)
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=REFERRAL_PAYOUT_CALLBACK,
        user=FakeUser(222, "u", "u2"),
        callback_id="cb_today",
    )

    await payout_button_callback(
        callback,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        payout_request_repo=mock_payout_repo,
        transaction_manager=mock_tm,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(
                referral_support_chat_id="",
                referral_stats_limit=10_000,
            ),
            admin=MagicMock(admin_base_url=""),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    mock_payout_repo.save.assert_not_called()
    assert len(client.answered_callbacks) == 1
    assert (
        "уже подавали заявку на вывод сегодня"
        in client.answered_callbacks[0]["text"]
    )


@pytest.mark.asyncio
async def test_payout_callback_rejects_when_pending_or_no_balance(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """payout_button_callback rejects when pending payout or balance <= 0."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(__user(external_id="333", username="u3"))
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_payout_repo = MagicMock()
    mock_payout_repo.save = AsyncMock(return_value=None)
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()

    for has_pending, income_total, paid_total, label in [
        (True, 100.0, 0.0, "has_pending_payout"),
        (False, 0.0, 0.0, "zero_balance"),
        (False, 50.0, 50.0, "zero_balance_after_paid"),
    ]:
        mock_income = MagicMock(spec=ReferralIncomeService)
        mock_income.get_user_referral_stats = AsyncMock(
            return_value=UserReferralStats(
                creators_count=0,
                orders_count=0,
                income_current_month=0.0,
                income_total=income_total,
                paid_total=paid_total,
                has_pending_payout=has_pending,
                has_request_today=False,
            )
        )
        callback = FakeCallback(
            data=REFERRAL_PAYOUT_CALLBACK,
            user=FakeUser(333, "u", "u3"),
            callback_id=f"cb_{label}",
        )
        await payout_button_callback(
            callback,
            user_role_service=user_role_service,
            referral_income_service=mock_income,
            payout_request_repo=mock_payout_repo,
            transaction_manager=mock_tm,
            config=MagicMock(
                spec=AppConfig,
                referral=MagicMock(
                    referral_support_chat_id="",
                    referral_stats_limit=10_000,
                ),
                admin=MagicMock(admin_base_url=""),
                market=MagicMock(currency_symbol="₽", default_locale="ru"),
            ),
            bot_texts_service=bot_texts_service,
            messenger_client=client,
            event_adapter=adapter,
        )
        assert not mock_payout_repo.save.called, (
            f"save should not be called for {label}"
        )
        assert any(
            "Выплата недоступна" in a.get("text", "")
            for a in client.answered_callbacks
        ), f"expected alert for {label}"


@pytest.mark.asyncio
async def test_payout_callback_support_send_failure_still_answers(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """When support channel send fails, callback is still answered."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(__user(external_id="777", username="u7"))
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=UserReferralStats(
            creators_count=0,
            orders_count=0,
            income_current_month=0.0,
            income_total=100.0,
            paid_total=0.0,
            has_pending_payout=False,
            has_request_today=False,
        )
    )
    mock_payout_repo = MagicMock()
    mock_payout_repo.save = AsyncMock(return_value=None)
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()

    client = FakeMessengerClient()

    async def send_text_fail(
        *, chat_id: str, text: str, **kwargs: object
    ) -> None:
        if chat_id == "support_chat":
            raise RuntimeError("Network error")

    client.send_text = send_text_fail
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=REFERRAL_PAYOUT_CALLBACK,
        user=FakeUser(777, "u", "u7"),
        callback_id="cb2",
    )

    await payout_button_callback(
        callback,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        payout_request_repo=mock_payout_repo,
        transaction_manager=mock_tm,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(
                referral_support_chat_id="support_chat",
                referral_stats_limit=10_000,
            ),
            admin=MagicMock(admin_base_url=""),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    answer_text = client.answered_callbacks[0]["text"]
    assert "не удалось уведомить поддержку" in answer_text
    assert "Обратитесь в поддержку вручную" in answer_text


@pytest.mark.asyncio
async def test_referral_command_user_not_found_sends_message(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """referral_command when user not in DB sends not-found message."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referral",
        user=FakeUser(99999, "unknown", "Unknown"),
    )

    await referral_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(referral_stats_limit=10_000),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    msg = client.sent_text[0]["text"]
    assert (
        "Пользователь не найден" in msg
        or "Профиль не найден" in msg
        or "not found" in msg.lower()
    )
    mock_income.get_user_referral_stats.assert_not_called()


@pytest.mark.asyncio
async def test_referral_command_admin_sees_another_user_stats(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """Admin /referral @username sees that user's stats, no payout button."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    admin_user = __user(
        external_id="1", username="admin", admin=True, telegram="admin"
    )
    other_user = __user(
        external_id="2",
        username="john",
        telegram="john",
        referral_code="ref_john",
    )
    await user_repo.save(admin_user)
    await user_repo.save(other_user)
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=UserReferralStats(
            creators_count=1,
            orders_count=2,
            income_current_month=10.0,
            income_total=50.0,
            paid_total=0.0,
            has_pending_payout=False,
            has_request_today=False,
        )
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referral @john", user=FakeUser(1, "admin", "admin")
    )

    await referral_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(
                referral_stats_limit=10_000,
                referral_bot_username="Bot",
            ),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    text = client.sent_text[0]["text"]
    assert "Реферальная статистика" in text or "Referral" in text or "1" in text
    assert (
        "Приведено креаторов: 1" in text
        or "Creators referred: 1" in text
        or "1" in text
    )
    assert "Накоплено (всего): 50.00" in text
    mock_income.get_user_referral_stats.assert_called_once_with(
        other_user.user_id, stats_limit=10_000
    )
    assert client.sent_text[0]["keyboard"] is None


@pytest.mark.asyncio
async def test_referral_command_admin_nonexistent_telegram_sends_user_not_found(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """Admin /referral @nonexistent sends user not found message."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    admin_user = __user(
        external_id="1", username="admin", admin=True, telegram="admin"
    )
    await user_repo.save(admin_user)
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referral @nonexistent", user=FakeUser(1, "admin", "admin")
    )

    await referral_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(referral_stats_limit=10_000),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    msg = client.sent_text[0]["text"]
    assert "Пользователь не найден" in msg or "not found" in msg.lower()
    mock_income.get_user_referral_stats.assert_not_called()


@pytest.mark.asyncio
async def test_referral_command_non_admin_with_arg_ignores_arg(
    user_repo: InMemoryUserRepository,
    bot_texts_service,
) -> None:
    """Non-admin /referral @someone shows own stats (arg ignored)."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    alice = __user(external_id="111", username="alice", telegram="alice")
    await user_repo.save(alice)
    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.get_user_referral_stats = AsyncMock(
        return_value=UserReferralStats(
            creators_count=0,
            orders_count=0,
            income_current_month=0.0,
            income_total=0.0,
            paid_total=0.0,
            has_pending_payout=False,
            has_request_today=False,
        )
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referral @someone_else", user=FakeUser(111, "u", "alice")
    )

    await referral_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(
            spec=AppConfig,
            referral=MagicMock(referral_stats_limit=10_000),
            market=MagicMock(currency_symbol="₽", default_locale="ru"),
        ),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    mock_income.get_user_referral_stats.assert_called_once_with(
        alice.user_id, stats_limit=10_000
    )
    assert "Реферальная статистика" in client.sent_text[0]["text"]


@pytest.mark.asyncio
async def test_referral_list_command_empty_sends_no_referrals_message(
    user_repo: InMemoryUserRepository,
    config,
    bot_texts_service,
) -> None:
    """referral_list_command with no referrals sends empty message."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(__user(external_id="789", username="carol"))
    user_role_service = UserRoleService(user_repo=user_repo)
    binding_repo = InMemoryUserReferralBindingRepository()
    pending_repo = InMemoryUserReferralPendingRepository()
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()

    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referral_list", user=FakeUser(789, "u", "carol")
    )

    await referral_list_command(
        message,
        user_role_service=user_role_service,
        user_referral_binding_repo=binding_repo,
        user_referral_pending_repo=pending_repo,
        user_repo=user_repo,
        referral_income_service=MagicMock(spec=ReferralIncomeService),
        transaction_manager=mock_tm,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    assert (
        "нет приведённых" in client.sent_text[0]["text"]
        or "no referred" in client.sent_text[0]["text"].lower()
    )


@pytest.mark.asyncio
async def test_referral_list_command_with_one_referral_sends_page(
    user_repo: InMemoryUserRepository,
    config,
    bot_texts_service,
) -> None:
    """referal_list with one referral sends page with name and orders count."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.domain.entities import User, UserReferralBinding
    from ugc_bot.domain.enums import MessengerType, UserStatus
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    referrer = __user(external_id="999", username="referrer")
    referred = User(
        user_id=uuid4(),
        external_id="refd",
        messenger_type=MessengerType.TELEGRAM,
        username="referred_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(referrer)
    await user_repo.save(referred)

    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer.user_id,
            referred_user_id=referred.user_id,
            created_at=datetime.now(timezone.utc),
        )
    )

    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.count_completed_orders_by_user_ids = AsyncMock(
        return_value={referred.user_id: 2}
    )

    pending_repo = InMemoryUserReferralPendingRepository()
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()

    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referral_list", user=FakeUser(999, "u", "referrer")
    )

    await referral_list_command(
        message,
        user_role_service=UserRoleService(user_repo=user_repo),
        user_referral_binding_repo=binding_repo,
        user_referral_pending_repo=pending_repo,
        user_repo=user_repo,
        referral_income_service=mock_income,
        transaction_manager=mock_tm,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    assert (
        "рефералы" in client.sent_text[0]["text"]
        or "referral" in client.sent_text[0]["text"].lower()
    )
    assert "referred_user" in client.sent_text[0]["text"]
    assert "выполнено заказов: 2" in client.sent_text[0]["text"]
    assert "Не заполнили профиль креатора" in client.sent_text[0]["text"]
    assert "Нет рефералов без профиля" in client.sent_text[0]["text"]


@pytest.mark.asyncio
async def test_referral_list_pagination_callback_edits_message(
    user_repo: InMemoryUserRepository,
    config,
    bot_texts_service,
) -> None:
    """referral_list_pagination_callback edits message with page and keys."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.domain.entities import User, UserReferralBinding
    from ugc_bot.domain.enums import MessengerType, UserStatus
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    referrer = __user(external_id="12345", username="pager_user")
    await user_repo.save(referrer)
    binding_repo = InMemoryUserReferralBindingRepository()
    for i in range(11):
        referred = User(
            user_id=uuid4(),
            external_id=f"ref{i}",
            messenger_type=MessengerType.TELEGRAM,
            username=f"referred_{i}",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
        await user_repo.save(referred)
        await binding_repo.save(
            UserReferralBinding(
                referrer_user_id=referrer.user_id,
                referred_user_id=referred.user_id,
                created_at=datetime.now(timezone.utc),
            )
        )

    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.count_completed_orders_by_user_ids = AsyncMock(
        side_effect=lambda user_ids, **kw: {uid: 0 for uid in user_ids}
    )
    pending_repo = InMemoryUserReferralPendingRepository()
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()

    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=f"{REFERRAL_LIST_CALLBACK_PREFIX}2",
        user=FakeUser(12345, "u", "pager_user"),
        callback_id="pag_cb",
        message=FakeMessage(
            text="",
            user=FakeUser(12345, "u", "pager_user"),
            message_id=100,
        ),
    )

    await referral_list_pagination_callback(
        callback,
        user_role_service=UserRoleService(user_repo=user_repo),
        user_referral_binding_repo=binding_repo,
        user_referral_pending_repo=pending_repo,
        user_repo=user_repo,
        referral_income_service=mock_income,
        transaction_manager=mock_tm,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.edited_text) == 1
    ed_text = client.edited_text[0]["text"]
    assert "страница 2/2" in ed_text or "page 2/2" in ed_text.lower()
    assert client.edited_text[0]["keyboard"] is not None
    assert len(client.answered_callbacks) == 1


@pytest.mark.asyncio
async def test_referral_list_pagination_callback_with_uuid_admin_ok(
    user_repo: InMemoryUserRepository,
    config,
    bot_texts_service,
) -> None:
    """Admin callback with referral_list:page:user_id shows that user's page."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.domain.entities import User, UserReferralBinding
    from ugc_bot.domain.enums import MessengerType, UserStatus
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    admin_user = __user(
        external_id="1", username="admin", admin=True, telegram="admin"
    )
    referrer = __user(external_id="2", username="john", telegram="john")
    await user_repo.save(admin_user)
    await user_repo.save(referrer)
    binding_repo = InMemoryUserReferralBindingRepository()
    for i in range(11):
        referred = User(
            user_id=uuid4(),
            external_id=f"r{i}",
            messenger_type=MessengerType.TELEGRAM,
            username=f"u{i}",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
        await user_repo.save(referred)
        await binding_repo.save(
            UserReferralBinding(
                referrer_user_id=referrer.user_id,
                referred_user_id=referred.user_id,
                created_at=datetime.now(timezone.utc),
            )
        )
    pending_repo = InMemoryUserReferralPendingRepository()
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.count_completed_orders_by_user_ids = AsyncMock(
        side_effect=lambda user_ids, **kw: {uid: 0 for uid in user_ids}
    )
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=f"{REFERRAL_LIST_CALLBACK_PREFIX}2:{referrer.user_id}",
        user=FakeUser(1, "admin", "admin"),
        callback_id="cb",
        message=FakeMessage(
            text="", user=FakeUser(1, "admin", "admin"), message_id=1
        ),
    )

    await referral_list_pagination_callback(
        callback,
        user_role_service=UserRoleService(user_repo=user_repo),
        user_referral_binding_repo=binding_repo,
        user_referral_pending_repo=pending_repo,
        user_repo=user_repo,
        referral_income_service=mock_income,
        transaction_manager=mock_tm,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.edited_text) == 1
    assert (
        "страница 2/2" in client.edited_text[0]["text"]
        or "page 2/2" in client.edited_text[0]["text"].lower()
    )
    assert len(client.answered_callbacks) == 1


@pytest.mark.asyncio
async def test_referral_list_pagination_callback_with_uuid_non_admin_denied(
    user_repo: InMemoryUserRepository,
    config,
    bot_texts_service,
) -> None:
    """Non-admin callback with referral_list:page:user_id gets access denied."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    regular = __user(external_id="99", username="regular", telegram="regular")
    other = __user(external_id="88", username="other", telegram="other")
    await user_repo.save(regular)
    await user_repo.save(other)
    binding_repo = InMemoryUserReferralBindingRepository()
    pending_repo = InMemoryUserReferralPendingRepository()
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=f"{REFERRAL_LIST_CALLBACK_PREFIX}1:{other.user_id}",
        user=FakeUser(99, "u", "regular"),
        callback_id="cb",
        message=FakeMessage(
            text="", user=FakeUser(99, "u", "regular"), message_id=1
        ),
    )

    await referral_list_pagination_callback(
        callback,
        user_role_service=UserRoleService(user_repo=user_repo),
        user_referral_binding_repo=binding_repo,
        user_referral_pending_repo=pending_repo,
        user_repo=user_repo,
        referral_income_service=mock_income,
        transaction_manager=mock_tm,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.edited_text) == 0
    assert len(client.answered_callbacks) == 1
    alert_text = client.answered_callbacks[0]["text"]
    assert "Доступ запрещён" in alert_text or "Access denied" in alert_text


@pytest.mark.asyncio
async def test_referral_list_command_only_pending_shows_block2_with_names(
    user_repo: InMemoryUserRepository,
    config,
    bot_texts_service,
) -> None:
    """referral_list with only pending shows block 2 with usernames."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.domain.entities import User, UserReferralPending
    from ugc_bot.domain.enums import MessengerType, UserStatus
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    referrer = __user(external_id="888", username="manager")
    pending_user = User(
        user_id=uuid4(),
        external_id="pend1",
        messenger_type=MessengerType.TELEGRAM,
        username="pending_blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        telegram="pending_blogger",
    )
    await user_repo.save(referrer)
    await user_repo.save(pending_user)

    binding_repo = InMemoryUserReferralBindingRepository()
    pending_repo = InMemoryUserReferralPendingRepository()
    await pending_repo.save(
        UserReferralPending(
            user_id=pending_user.user_id,
            referrer_user_id=referrer.user_id,
            created_at=datetime.now(timezone.utc),
        )
    )

    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()

    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referral_list", user=FakeUser(888, "u", "manager")
    )

    await referral_list_command(
        message,
        user_role_service=UserRoleService(user_repo=user_repo),
        user_referral_binding_repo=binding_repo,
        user_referral_pending_repo=pending_repo,
        user_repo=user_repo,
        referral_income_service=mock_income,
        transaction_manager=mock_tm,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    text = client.sent_text[0]["text"]
    assert (
        "Ваши рефералы: пока никого" in text
        or "referrals: none" in text.lower()
    )
    assert (
        "Не заполнили профиль креатора" in text
        or "creator profile" in text.lower()
    )
    assert "pending_blogger" in text or "@pending_blogger" in text


@pytest.mark.asyncio
async def test_referral_list_command_both_bindings_and_pending_shows_two_blocks(
    user_repo: InMemoryUserRepository,
    config,
    bot_texts_service,
) -> None:
    """referral_list with bindings and pending shows both blocks filled."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.domain.entities import (
        User,
        UserReferralBinding,
        UserReferralPending,
    )
    from ugc_bot.domain.enums import MessengerType, UserStatus
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    referrer = __user(external_id="777", username="manager2")
    referred = User(
        user_id=uuid4(),
        external_id="refd2",
        messenger_type=MessengerType.TELEGRAM,
        username="referred_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    pending_user = User(
        user_id=uuid4(),
        external_id="pend2",
        messenger_type=MessengerType.TELEGRAM,
        username="pending_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(referrer)
    await user_repo.save(referred)
    await user_repo.save(pending_user)

    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer.user_id,
            referred_user_id=referred.user_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    pending_repo = InMemoryUserReferralPendingRepository()
    await pending_repo.save(
        UserReferralPending(
            user_id=pending_user.user_id,
            referrer_user_id=referrer.user_id,
            created_at=datetime.now(timezone.utc),
        )
    )

    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.count_completed_orders_by_user_ids = AsyncMock(
        side_effect=lambda user_ids, **kw: {uid: 0 for uid in user_ids}
    )
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()

    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referral_list", user=FakeUser(777, "u", "manager2")
    )

    await referral_list_command(
        message,
        user_role_service=UserRoleService(user_repo=user_repo),
        user_referral_binding_repo=binding_repo,
        user_referral_pending_repo=pending_repo,
        user_repo=user_repo,
        referral_income_service=mock_income,
        transaction_manager=mock_tm,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    text = client.sent_text[0]["text"]
    assert ("Ваши рефералы" in text or "referral" in text.lower()) and (
        "страница" in text or "page" in text.lower()
    )
    assert "referred_user" in text
    assert "Не заполнили профиль креатора" in text
    assert "pending_user" in text


@pytest.mark.asyncio
async def test_referral_list_command_user_not_found_sends_message(
    user_repo: InMemoryUserRepository,
    config,
    bot_texts_service,
) -> None:
    """referral_list when user not in repo sends user not found."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    user_role_service = UserRoleService(user_repo=user_repo)
    binding_repo = InMemoryUserReferralBindingRepository()
    pending_repo = InMemoryUserReferralPendingRepository()
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referral_list", user=FakeUser(99999, "u", "unknown")
    )

    await referral_list_command(
        message,
        user_role_service=user_role_service,
        user_referral_binding_repo=binding_repo,
        user_referral_pending_repo=pending_repo,
        user_repo=user_repo,
        referral_income_service=MagicMock(spec=ReferralIncomeService),
        transaction_manager=mock_tm,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    msg = client.sent_text[0]["text"]
    assert (
        "Пользователь не найден" in msg
        or "Профиль не найден" in msg
        or "not found" in msg.lower()
        or "profile" in msg.lower()
    )


@pytest.mark.asyncio
async def test_referral_list_command_admin_sees_another_user_list(
    user_repo: InMemoryUserRepository,
    config,
    bot_texts_service,
) -> None:
    """Admin /referral_list @username sees that user list; callback has uuid."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.domain.entities import User, UserReferralBinding
    from ugc_bot.domain.enums import MessengerType, UserStatus
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    admin_user = __user(
        external_id="1", username="admin", admin=True, telegram="admin"
    )
    john = __user(external_id="2", username="john", telegram="john")
    await user_repo.save(admin_user)
    await user_repo.save(john)
    binding_repo = InMemoryUserReferralBindingRepository()
    for i in range(11):
        referred = User(
            user_id=uuid4(),
            external_id=f"refd{i}",
            messenger_type=MessengerType.TELEGRAM,
            username=f"referred_{i}",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
        await user_repo.save(referred)
        await binding_repo.save(
            UserReferralBinding(
                referrer_user_id=john.user_id,
                referred_user_id=referred.user_id,
                created_at=datetime.now(timezone.utc),
            )
        )
    pending_repo = InMemoryUserReferralPendingRepository()
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.count_completed_orders_by_user_ids = AsyncMock(
        side_effect=lambda user_ids, **kw: {uid: 0 for uid in user_ids}
    )
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referral_list @john", user=FakeUser(1, "admin", "admin")
    )

    await referral_list_command(
        message,
        user_role_service=UserRoleService(user_repo=user_repo),
        user_referral_binding_repo=binding_repo,
        user_referral_pending_repo=pending_repo,
        user_repo=user_repo,
        referral_income_service=mock_income,
        transaction_manager=mock_tm,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    text = client.sent_text[0]["text"]
    assert ("рефералы" in text or "referral" in text.lower()) and (
        "страница" in text or "page" in text.lower()
    )
    keyboard = client.sent_text[0].get("keyboard")
    assert keyboard is not None
    callback_datas = []
    for row in getattr(keyboard, "rows", []) or []:
        for btn in row:
            cd = getattr(btn, "callback_data", None)
            if cd:
                callback_datas.append(cd)
    assert any(str(john.user_id) in cd for cd in callback_datas), callback_datas


@pytest.mark.asyncio
async def test_referral_list_pagination_callback_invalid_page_uses_one(
    user_repo: InMemoryUserRepository,
    config,
    bot_texts_service,
) -> None:
    """referral_list callback with non-numeric data uses page 1."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.domain.entities import User, UserReferralBinding
    from ugc_bot.domain.enums import MessengerType, UserStatus
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    referrer = __user(external_id="555", username="ref")
    await user_repo.save(referrer)
    binding_repo = InMemoryUserReferralBindingRepository()
    for i in range(3):
        u = User(
            user_id=uuid4(),
            external_id=f"x{i}",
            messenger_type=MessengerType.TELEGRAM,
            username=f"u{i}",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
        await user_repo.save(u)
        await binding_repo.save(
            UserReferralBinding(
                referrer_user_id=referrer.user_id,
                referred_user_id=u.user_id,
                created_at=datetime.now(timezone.utc),
            )
        )
    pending_repo = InMemoryUserReferralPendingRepository()
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.count_completed_orders_by_user_ids = AsyncMock(
        side_effect=lambda user_ids, **kw: {uid: 0 for uid in user_ids}
    )
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=f"{REFERRAL_LIST_CALLBACK_PREFIX}abc",
        user=FakeUser(555, "u", "ref"),
        callback_id="cb",
        message=FakeMessage(
            text="", user=FakeUser(555, "u", "ref"), message_id=1
        ),
    )

    await referral_list_pagination_callback(
        callback,
        user_role_service=UserRoleService(user_repo=user_repo),
        user_referral_binding_repo=binding_repo,
        user_referral_pending_repo=pending_repo,
        user_repo=user_repo,
        referral_income_service=mock_income,
        transaction_manager=mock_tm,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.edited_text) == 1
    ed = client.edited_text[0]["text"]
    assert "страница 1/1" in ed or "page 1/1" in ed.lower()


@pytest.mark.asyncio
async def test_referral_list_command_page1_shows_forward_button(
    user_repo: InMemoryUserRepository,
    config,
    bot_texts_service,
) -> None:
    """referral_list page 1 with multiple pages shows Вперёд button."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.domain.entities import User, UserReferralBinding
    from ugc_bot.domain.enums import MessengerType, UserStatus
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    referrer = __user(external_id="444", username="mgr")
    await user_repo.save(referrer)
    binding_repo = InMemoryUserReferralBindingRepository()
    for i in range(11):
        u = User(
            user_id=uuid4(),
            external_id=f"y{i}",
            messenger_type=MessengerType.TELEGRAM,
            username=f"u{i}",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
        await user_repo.save(u)
        await binding_repo.save(
            UserReferralBinding(
                referrer_user_id=referrer.user_id,
                referred_user_id=u.user_id,
                created_at=datetime.now(timezone.utc),
            )
        )
    pending_repo = InMemoryUserReferralPendingRepository()
    mock_income = MagicMock(spec=ReferralIncomeService)
    mock_income.count_completed_orders_by_user_ids = AsyncMock(
        side_effect=lambda user_ids, **kw: {uid: 0 for uid in user_ids}
    )
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(text="/referral_list", user=FakeUser(444, "u", "mgr"))

    await referral_list_command(
        message,
        user_role_service=UserRoleService(user_repo=user_repo),
        user_referral_binding_repo=binding_repo,
        user_referral_pending_repo=pending_repo,
        user_repo=user_repo,
        referral_income_service=mock_income,
        transaction_manager=mock_tm,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    keyboard = client.sent_text[0].get("keyboard")
    assert keyboard is not None
    forward_texts = [
        btn.text for row in keyboard.rows for btn in row if btn.text == "Вперёд"
    ]
    assert len(forward_texts) == 1


def __fake_tx():
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _tx():
        yield object()

    return _tx()


def __user(
    *,
    external_id: str,
    username: str,
    referral_code: str | None = None,
    admin: bool = False,
    telegram: str | None = None,
):
    """Build minimal User for tests."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from ugc_bot.domain.entities import User
    from ugc_bot.domain.enums import MessengerType, UserStatus

    return User(
        user_id=uuid4(),
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username=username,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        referral_code=referral_code,
        admin=admin,
        telegram=telegram,
    )
