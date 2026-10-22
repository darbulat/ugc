"""Rating FSM branch outcomes with real FSM storage and rating service."""

from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, User

from ugc_bot.application.services.blogger_rating_service import (
    BloggerRatingService,
)
from ugc_bot.bot.telegram.handlers import blogger_rating as handlers
from ugc_bot.domain.enums import MessengerType, RaterRole
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerRatingRepository,
)


@pytest.fixture
def flow():
    state = FSMContext(
        MemoryStorage(), StorageKey(bot_id=1, chat_id=2, user_id=3)
    )
    order_id, blogger_id, user_id = uuid4(), uuid4(), uuid4()
    roles = NS(
        get_user=AsyncMock(return_value=NS(user_id=user_id)),
        get_user_by_id=AsyncMock(return_value=NS(admin=False)),
    )
    managers = NS(is_manager_for_order=AsyncMock(return_value=False))
    repo = InMemoryBloggerRatingRepository()
    return NS(
        state=state,
        order_id=order_id,
        blogger_id=blogger_id,
        user_id=user_id,
        roles=roles,
        managers=managers,
        repo=repo,
        service=BloggerRatingService(repo),
    )


def message(text="  Great work  ", from_user=True):
    event = Mock(spec=Message)
    event.text = text
    event.from_user = (
        User(id=3, is_bot=False, first_name="Tester") if from_user else None
    )
    event.answer = AsyncMock()
    return event


def callback(data=None, with_message=True):
    event = Mock(spec=CallbackQuery)
    event.data = data
    event.from_user = User(id=3, is_bot=False, first_name="Tester")
    event.message = message() if with_message else None
    event.answer = AsyncMock()
    return event


async def select_score(flow, score=4):
    event = callback(f"brs:{flow.order_id}:{flow.blogger_id}:{score}")
    await handlers.handle_rating_score(event, flow.state)
    return event


@pytest.mark.asyncio
async def test_prompt_has_five_stars_and_preserves_identifiers(flow):
    event = message()
    await handlers.send_order_rating_prompt(
        event, flow.order_id, flow.blogger_id
    )
    args, kwargs = event.answer.await_args
    assert args == ("Оцените работу креатора от 1 до 5:",)
    buttons = kwargs["reply_markup"].inline_keyboard[0]
    assert [b.text for b in buttons] == [f"{score} ⭐" for score in range(1, 6)]
    assert [b.callback_data for b in buttons] == [
        f"brs:{flow.order_id}:{flow.blogger_id}:{score}"
        for score in range(1, 6)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("has_message", [False, True])
async def test_score_selection_records_real_fsm_state(flow, has_message):
    event = callback(f"brs:{flow.order_id}:{flow.blogger_id}:5", has_message)
    await handlers.handle_rating_score(event, flow.state)
    assert (
        await flow.state.get_state()
        == handlers.RatingStates.waiting_comment.state
    )
    assert await flow.state.get_data() == dict(
        order_id=str(flow.order_id), blogger_id=str(flow.blogger_id), score=5
    )
    event.answer.assert_awaited_once_with()
    if has_message:
        markup = event.message.answer.await_args.kwargs["reply_markup"]
        assert markup.inline_keyboard[0][0].callback_data == "brc:skip"


@pytest.mark.asyncio
async def test_missing_callback_data_leaves_state_untouched(flow):
    event = callback()
    await handlers.handle_rating_score(event, flow.state)
    assert await flow.state.get_data() == {}
    assert await flow.state.get_state() is None
    event.answer.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(RaterRole))
@pytest.mark.parametrize("skip", [False, True])
async def test_complete_rating_flow_persists_role_score_and_comment(
    flow, role, skip
):
    flow.roles.get_user_by_id.return_value.admin = role == RaterRole.ADMIN
    flow.managers.is_manager_for_order.return_value = role == RaterRole.MANAGER
    await select_score(flow)
    event = callback("brc:skip") if skip else message()
    handler = (
        handlers.handle_skip_comment if skip else handlers.handle_rating_comment
    )
    await handler(event, flow.state, flow.service, flow.roles, flow.managers)
    ratings = list(flow.repo.ratings)
    assert len(ratings) == 1
    rating = ratings[0]
    assert (rating.blogger_id, rating.order_id, rating.rater_id) == (
        flow.blogger_id,
        flow.order_id,
        flow.user_id,
    )
    assert (rating.score, rating.comment, rating.rater_role) == (
        4,
        None if skip else "Great work",
        role,
    )
    assert rating.created_at <= datetime.now(timezone.utc)
    flow.roles.get_user.assert_awaited_once_with(
        external_id="3",
        messenger_type=MessengerType.TELEGRAM,
    )
    if role == RaterRole.ADMIN:
        flow.managers.is_manager_for_order.assert_not_awaited()
    else:
        flow.managers.is_manager_for_order.assert_awaited_once_with(
            flow.user_id, flow.order_id
        )
    assert await flow.state.get_data() == {}
    assert await flow.state.get_state() is None
    target = event.message if skip else event
    target.answer.assert_awaited_once_with("Спасибо, оценка сохранена.")
    if skip:
        event.answer.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,expected",
    [
        ("expired", "Сессия оценки истекла. Попробуйте снова."),
        ("unknown", "Пользователь не найден."),
        ("invalid", "Оценка должна быть от 1 до 5."),
        ("duplicate", "Оценка для этого заказа уже сохранена."),
        ("anonymous", None),
    ],
)
async def test_unsavable_rating_clears_session_and_reports_reason(
    flow, case, expected
):
    if case != "expired":
        await select_score(flow, score=8 if case == "invalid" else 4)
    if case == "unknown":
        flow.roles.get_user.return_value = None
    if case == "duplicate":
        await flow.service.rate_blogger(
            flow.blogger_id,
            flow.order_id,
            flow.user_id,
            RaterRole.ADVERTISER,
            3,
        )
    event = message(from_user=case != "anonymous")
    await handlers.handle_rating_comment(
        event, flow.state, flow.service, flow.roles, flow.managers
    )
    assert len(flow.repo.ratings) == int(case == "duplicate")
    assert await flow.state.get_data() == {}
    assert await flow.state.get_state() is None
    if expected:
        event.answer.assert_awaited_once_with(expected)
    else:
        event.answer.assert_not_awaited()
    if case in {"expired", "anonymous"}:
        flow.roles.get_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_without_message_is_acknowledged_on_expired_session(
    flow,
):
    event = callback("brc:skip", with_message=False)
    await handlers.handle_skip_comment(
        event, flow.state, flow.service, flow.roles, flow.managers
    )
    event.answer.assert_awaited_once_with()
    assert not flow.repo.ratings


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [None, " \n "])
async def test_empty_comment_is_saved_as_none(flow, text):
    await select_score(flow)
    await handlers.handle_rating_comment(
        message(text), flow.state, flow.service, flow.roles, flow.managers
    )
    assert next(iter(flow.repo.ratings)).comment is None


@pytest.mark.asyncio
async def test_missing_user_record_resolves_nonmanager_as_advertiser(flow):
    flow.roles.get_user_by_id.return_value = None
    result = await handlers._resolve_rater_role(
        flow.user_id, flow.order_id, flow.roles, flow.managers
    )
    assert result == RaterRole.ADVERTISER
