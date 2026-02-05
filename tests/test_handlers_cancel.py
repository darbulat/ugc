"""Tests for Support button (replaces former cancel handler)."""

import pytest

from tests.helpers.fakes import (
    FakeFSMContext,
    FakeFsmDraftService,
    FakeMessage,
    FakeUser,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.start import support_button


@pytest.mark.asyncio
async def test_support_button_sends_support_text_and_menu(user_repo) -> None:
    """Support button sends support text and main menu keyboard."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text="Поддержка", user=FakeUser(1, "u", "User"))
    state = FakeFSMContext(state=None)
    draft_service = FakeFsmDraftService()

    await support_button(
        message,
        user_role_service=service,
        state=state,
        fsm_draft_service=draft_service,
    )

    assert message.answers
    text = (
        message.answers[0][0]
        if isinstance(message.answers[0], tuple)
        else message.answers[0]
    )
    assert "Служба поддержки" in text
    assert "@usemycontent" in text
    assert "Обращайтесь по любым вопросам" in text


@pytest.mark.asyncio
async def test_support_button_clears_state_when_in_fsm(user_repo) -> None:
    """Support button clears FSM state and shows support."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text="Поддержка", user=FakeUser(2, "u", "User"))
    state = FakeFSMContext(state="OrderCreationStates:product_link")
    draft_service = FakeFsmDraftService()

    await support_button(
        message,
        user_role_service=service,
        state=state,
        fsm_draft_service=draft_service,
    )

    assert state.cleared is True
    text = (
        message.answers[0][0]
        if isinstance(message.answers[0], tuple)
        else message.answers[0]
    )
    assert "Служба поддержки" in text
