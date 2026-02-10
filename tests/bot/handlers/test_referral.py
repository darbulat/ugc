"""Tests for referral handlers: /referal, payout, /referal_list."""

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
    referal_command,
    referal_list_command,
    referal_list_pagination_callback,
)
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryUserReferralBindingRepository,
    InMemoryUserRepository,
)


@pytest.mark.asyncio
async def test_referal_command_sends_stats_and_keyboard(
    user_repo: InMemoryUserRepository,
) -> None:
    """referal_command sends referral stats and payout keyboard."""
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
        )
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(text="/referal", user=FakeUser(123, "u", "alice"))

    await referal_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(spec=AppConfig),
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    assert "Реферальная статистика" in client.sent_text[0]["text"]
    assert "Приведено креаторов: 0" in client.sent_text[0]["text"]
    assert "Выплачено: 0.00" in client.sent_text[0]["text"]
    assert "Текущий баланс: 0.00" in client.sent_text[0]["text"]
    # No payout button when balance is zero
    assert client.sent_text[0]["keyboard"] is None


@pytest.mark.asyncio
async def test_referal_command_shows_payout_button_when_balance_positive(
    user_repo: InMemoryUserRepository,
) -> None:
    """referal_command shows payout keyboard when income_total > 0."""
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
        )
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(text="/referal", user=FakeUser(456, "u", "bob"))

    await referal_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(spec=AppConfig),
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    assert "Выплачено: 0.00" in client.sent_text[0]["text"]
    assert "Текущий баланс: 500.00" in client.sent_text[0]["text"]
    assert client.sent_text[0]["keyboard"] is not None


@pytest.mark.asyncio
async def test_referal_command_hides_payout_button_when_pending_request(
    user_repo: InMemoryUserRepository,
) -> None:
    """referal_command hides payout keyboard when has_pending_payout is True."""
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
        )
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(text="/referal", user=FakeUser(789, "u", "carol"))

    await referal_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(spec=AppConfig),
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    assert "Текущий баланс: 100.00" in client.sent_text[0]["text"]
    assert client.sent_text[0]["keyboard"] is None


@pytest.mark.asyncio
async def test_payout_button_callback_creates_request_and_answers(
    user_repo: InMemoryUserRepository,
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
            referral=MagicMock(referral_support_chat_id=""),
            admin=MagicMock(admin_base_url=""),
        ),
        messenger_client=client,
        event_adapter=adapter,
    )

    assert mock_payout_repo.save.called
    assert any(
        "Запрос на выплату отправлен" in a.get("text", "")
        for a in client.answered_callbacks
    )


@pytest.mark.asyncio
async def test_payout_callback_includes_admin_link_when_base_url_set(
    user_repo: InMemoryUserRepository,
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
            referral=MagicMock(referral_support_chat_id="support_chat"),
            admin=MagicMock(admin_base_url="https://admin.example.com/admin"),
        ),
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    assert client.sent_text[0]["chat_id"] == "support_chat"
    assert "Открыть в админке" in client.sent_text[0]["text"]
    assert "payoutrequestmodel/edit/" in client.sent_text[0]["text"]


@pytest.mark.asyncio
async def test_payout_callback_support_send_failure_still_answers(
    user_repo: InMemoryUserRepository,
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
            referral=MagicMock(referral_support_chat_id="support_chat"),
            admin=MagicMock(admin_base_url=""),
        ),
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert "Запрос на выплату отправлен" in client.answered_callbacks[0]["text"]


@pytest.mark.asyncio
async def test_referal_command_user_not_found_sends_message(
    user_repo: InMemoryUserRepository,
) -> None:
    """referal_command when user not in DB sends not-found message."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    user_role_service = UserRoleService(user_repo=user_repo)
    mock_income = MagicMock(spec=ReferralIncomeService)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referal",
        user=FakeUser(99999, "unknown", "Unknown"),
    )

    await referal_command(
        message,
        user_role_service=user_role_service,
        referral_income_service=mock_income,
        config=MagicMock(spec=AppConfig),
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    assert "Пользователь не найден" in client.sent_text[0]["text"]
    mock_income.get_user_referral_stats.assert_not_called()


@pytest.mark.asyncio
async def test_referal_list_command_empty_sends_no_referrals_message(
    user_repo: InMemoryUserRepository,
) -> None:
    """referal_list_command with no referrals sends empty message."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.infrastructure.messenger.telegram.adapter import (
        TelegramEventAdapter,
    )

    await user_repo.save(__user(external_id="789", username="carol"))
    user_role_service = UserRoleService(user_repo=user_repo)
    binding_repo = InMemoryUserReferralBindingRepository()
    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()

    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referal_list", user=FakeUser(789, "u", "carol")
    )

    await referal_list_command(
        message,
        user_role_service=user_role_service,
        user_referral_binding_repo=binding_repo,
        user_repo=user_repo,
        referral_income_service=MagicMock(spec=ReferralIncomeService),
        transaction_manager=mock_tm,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    assert "нет приведённых" in client.sent_text[0]["text"]


@pytest.mark.asyncio
async def test_referal_list_command_with_one_referral_sends_page(
    user_repo: InMemoryUserRepository,
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
    mock_income.count_completed_orders_for_user = AsyncMock(return_value=2)

    mock_tm = MagicMock()
    mock_tm.transaction = lambda: __fake_tx()

    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text="/referal_list", user=FakeUser(999, "u", "referrer")
    )

    await referal_list_command(
        message,
        user_role_service=UserRoleService(user_repo=user_repo),
        user_referral_binding_repo=binding_repo,
        user_repo=user_repo,
        referral_income_service=mock_income,
        transaction_manager=mock_tm,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 1
    assert "рефералы" in client.sent_text[0]["text"]
    assert "referred_user" in client.sent_text[0]["text"]
    assert "выполнено заказов: 2" in client.sent_text[0]["text"]


@pytest.mark.asyncio
async def test_referal_list_pagination_callback_edits_message(
    user_repo: InMemoryUserRepository,
) -> None:
    """referal_list_pagination_callback edits message with page and keyboard."""
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
    mock_income.count_completed_orders_for_user = AsyncMock(return_value=0)
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

    await referal_list_pagination_callback(
        callback,
        user_role_service=UserRoleService(user_repo=user_repo),
        user_referral_binding_repo=binding_repo,
        user_repo=user_repo,
        referral_income_service=mock_income,
        transaction_manager=mock_tm,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.edited_text) == 1
    assert "страница 2/2" in client.edited_text[0]["text"]
    assert client.edited_text[0]["keyboard"] is not None
    assert len(client.answered_callbacks) == 1


def __fake_tx():
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _tx():
        yield object()

    return _tx()


def __user(*, external_id: str, username: str):
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
    )
