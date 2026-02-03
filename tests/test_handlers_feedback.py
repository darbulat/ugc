"""Tests for feedback handler."""

import pytest
from uuid import UUID

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.feedback import handle_feedback
from ugc_bot.domain.enums import AudienceGender, InteractionStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryNpsRepository
from tests.helpers.fakes import FakeCallback, FakeFSMContext, FakeMessage, FakeUser
from tests.helpers.factories import create_test_interaction, create_test_user


@pytest.fixture
def nps_repo() -> InMemoryNpsRepository:
    """In-memory NPS repository for tests."""
    return InMemoryNpsRepository()


@pytest.mark.asyncio
async def test_feedback_handler_advertiser_ok(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Advertiser feedback updates interaction."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000930"),
        external_id="42",
        username="adv",
    )

    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000000932"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000933"),
        advertiser_id=advertiser.user_id,
        interaction_id=UUID("00000000-0000-0000-0000-000000000931"),
    )

    callback = FakeCallback(
        data=f"feedback:adv:{interaction.interaction_id}:ok", user=FakeUser(42)
    )
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)

    assert callback.answers
    updated = await interaction_repo.get_by_id(interaction.interaction_id)
    assert updated is not None
    assert updated.from_advertiser == "✅ Всё прошло нормально"


@pytest.mark.asyncio
async def test_feedback_handler_wrong_user(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Reject feedback from unrelated user."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000940"),
        external_id="100",
        username="adv",
    )
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000944"),
        external_id="999",
        username="other",
    )
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000000942"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000943"),
        advertiser_id=advertiser.user_id,
        interaction_id=UUID("00000000-0000-0000-0000-000000000941"),
    )

    callback = FakeCallback(
        data=f"feedback:adv:{interaction.interaction_id}:ok", user=FakeUser(999)
    )
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)
    assert "Недостаточно прав." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_no_callback_data(
    user_repo, interaction_repo, nps_repo
) -> None:
    """When callback has no data, return without error."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    callback = FakeCallback(
        data="feedback:adv:00000000-0000-0000-0000-000000000001:ok", user=FakeUser(1)
    )
    callback.data = None
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)
    assert not callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_invalid_format(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Reject malformed callback data."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    callback = FakeCallback(data="feedback:bad", user=FakeUser(1))
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)
    assert "Неверный формат ответа." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_invalid_status(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Reject unknown status values."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    callback = FakeCallback(
        data="feedback:adv:00000000-0000-0000-0000-000000000999:bad", user=FakeUser(1)
    )
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)
    assert "Неверный статус." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_invalid_uuid(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Reject invalid UUID values."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    callback = FakeCallback(data="feedback:adv:not-a-uuid:ok", user=FakeUser(1))
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)
    assert "Неверный идентификатор." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_user_not_found(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Reject when user is missing."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    callback = FakeCallback(
        data="feedback:adv:00000000-0000-0000-0000-000000001000:ok",
        user=FakeUser(123),
    )
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)
    assert "Пользователь не найден." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_no_from_user(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Handle callback without from_user."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    callback = FakeCallback(
        data="feedback:adv:00000000-0000-0000-0000-000000001001:ok",
        user=FakeUser(123),
    )
    callback.from_user = None
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)
    assert not callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_interaction_not_found(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Handle missing interaction."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001010"),
        external_id="1010",
        username="adv",
    )

    callback = FakeCallback(
        data=f"feedback:adv:{UUID('00000000-0000-0000-0000-000000001011')}:ok",
        user=FakeUser(1010),
    )
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)
    assert "Взаимодействие не найдено." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_blogger_wrong_user(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Reject feedback from unrelated blogger."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001020"),
        external_id="1020",
        username="blogger",
    )
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001024"),
        external_id="9999",
        username="other",
    )

    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001022"),
        blogger_id=blogger.user_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000001023"),
        interaction_id=UUID("00000000-0000-0000-0000-000000001021"),
    )

    callback = FakeCallback(
        data=f"feedback:blog:{interaction.interaction_id}:ok", user=FakeUser(9999)
    )
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)
    assert "Недостаточно прав." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_blogger_feedback(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Blogger feedback updates interaction."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001030"),
        external_id="1030",
        username="blogger",
    )

    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001032"),
        blogger_id=blogger.user_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000001033"),
        interaction_id=UUID("00000000-0000-0000-0000-000000001031"),
    )

    callback = FakeCallback(
        data=f"feedback:blog:{interaction.interaction_id}:ok", user=FakeUser(1030)
    )
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)

    assert callback.answers
    updated = await interaction_repo.get_by_id(interaction.interaction_id)
    assert updated is not None
    assert updated.from_blogger == "✅ Всё прошло нормально"


@pytest.mark.asyncio
async def test_feedback_handler_postpone(user_repo, interaction_repo, nps_repo) -> None:
    """Handle postpone feedback with remaining postpones."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(
        interaction_repo=interaction_repo, max_postpone_count=3
    )

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001040"),
        external_id="1040",
        username="adv",
    )

    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001042"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001043"),
        advertiser_id=advertiser.user_id,
        interaction_id=UUID("00000000-0000-0000-0000-000000001041"),
        postpone_count=1,
    )

    callback = FakeCallback(
        data=f"feedback:adv:{interaction.interaction_id}:postpone", user=FakeUser(1040)
    )
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)

    assert any("перенесена" in ans for ans in callback.answers)
    assert any("2/3" in ans for ans in callback.answers)


@pytest.mark.asyncio
async def test_feedback_handler_postpone_max_reached(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Handle postpone feedback when max postpones reached."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(
        interaction_repo=interaction_repo, max_postpone_count=3
    )

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001050"),
        external_id="1050",
        username="adv",
    )

    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001052"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001053"),
        advertiser_id=advertiser.user_id,
        interaction_id=UUID("00000000-0000-0000-0000-000000001051"),
        postpone_count=3,
    )

    callback = FakeCallback(
        data=f"feedback:adv:{interaction.interaction_id}:postpone", user=FakeUser(1050)
    )
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)

    assert any("максимум переносов" in ans for ans in callback.answers)
    updated = await interaction_repo.get_by_id(interaction.interaction_id)
    assert updated is not None
    assert updated.status == InteractionStatus.NO_DEAL


@pytest.mark.asyncio
async def test_feedback_handler_exception(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Handle exceptions gracefully."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001060"),
        external_id="1060",
        username="adv",
    )

    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001062"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001063"),
        advertiser_id=advertiser.user_id,
        interaction_id=UUID("00000000-0000-0000-0000-000000001061"),
    )

    # Mock interaction_service to raise exception
    original_get_by_id = interaction_service.interaction_repo.get_by_id

    def failing_get_by_id(interaction_id: UUID):
        if interaction_id == interaction.interaction_id:
            raise Exception("Test exception")
        return original_get_by_id(interaction_id)

    interaction_service.interaction_repo.get_by_id = failing_get_by_id  # type: ignore[assignment]

    callback = FakeCallback(
        data=f"feedback:adv:{interaction.interaction_id}:ok", user=FakeUser(1060)
    )
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)

    assert any("ошибка" in ans.lower() for ans in callback.answers)


@pytest.mark.asyncio
async def test_feedback_handler_no_deal_shows_reason_keyboard(
    user_repo, interaction_repo, nps_repo
) -> None:
    """When user selects no_deal, show reason keyboard (do not record yet)."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001070"),
        external_id="1070",
        username="adv",
    )
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001072"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001073"),
        advertiser_id=advertiser.user_id,
        interaction_id=UUID("00000000-0000-0000-0000-000000001071"),
    )

    callback = FakeCallback(
        data=f"feedback:adv:{interaction.interaction_id}:no_deal", user=FakeUser(1070)
    )
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)

    assert callback.message.answers
    assert any("причине" in str(a) for a in callback.message.answers)


@pytest.mark.asyncio
async def test_feedback_handler_nps_saves_score(
    user_repo, interaction_repo, nps_repo
) -> None:
    """NPS callback saves score and answers."""

    from ugc_bot.bot.handlers.feedback import handle_nps

    user_service = UserRoleService(user_repo=user_repo)
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001080"),
        external_id="1080",
        username="adv",
    )
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001082"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001083"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001080"),
        interaction_id=UUID("00000000-0000-0000-0000-000000001081"),
    )

    callback = FakeCallback(
        data=f"nps:{interaction.interaction_id}:4", user=FakeUser(1080)
    )
    await handle_nps(callback, user_service, nps_repo)

    assert "Спасибо" in callback.answers[0]
    assert nps_repo.scores.get(interaction.interaction_id) == [4]


@pytest.mark.asyncio
async def test_handle_nps_no_callback_data(
    user_repo, interaction_repo, nps_repo
) -> None:
    """When callback has no data, return without error."""

    from ugc_bot.bot.handlers.feedback import handle_nps

    user_service = UserRoleService(user_repo=user_repo)
    callback = FakeCallback(
        data="nps:00000000-0000-0000-0000-000000001081:4", user=FakeUser(1)
    )
    callback.data = None
    await handle_nps(callback, user_service, nps_repo)
    assert not callback.answers


@pytest.mark.asyncio
async def test_handle_nps_wrong_parts_count(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Reject nps callback with wrong number of parts."""

    from ugc_bot.bot.handlers.feedback import handle_nps

    user_service = UserRoleService(user_repo=user_repo)
    callback = FakeCallback(data="nps:uuid", user=FakeUser(1))
    await handle_nps(callback, user_service, nps_repo)
    assert "Неверный формат." in callback.answers


@pytest.mark.asyncio
async def test_handle_nps_score_out_of_range(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Reject nps score not in 1-5."""

    from ugc_bot.bot.handlers.feedback import handle_nps

    user_service = UserRoleService(user_repo=user_repo)
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001085"),
        external_id="1085",
        username="adv",
    )
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001086"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001087"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001085"),
        interaction_id=UUID("00000000-0000-0000-0000-000000001088"),
    )
    callback = FakeCallback(
        data=f"nps:{interaction.interaction_id}:0", user=FakeUser(1085)
    )
    await handle_nps(callback, user_service, nps_repo)
    assert "1 до 5" in callback.answers[0]


@pytest.mark.asyncio
async def test_feedback_reason_records_and_marks_blogger(
    user_repo,
    interaction_repo,
    blogger_repo,
) -> None:
    """When advertiser selects 'Креатор хотел изменить условия', reason is recorded and blogger marked."""

    from datetime import datetime, timezone

    from ugc_bot.bot.handlers.feedback import handle_feedback_reason
    from ugc_bot.domain.entities import BloggerProfile
    from ugc_bot.domain.enums import WorkFormat
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryBloggerProfileRepository,
    )

    from ugc_bot.application.services.blogger_registration_service import (
        BloggerRegistrationService,
    )

    if not isinstance(blogger_repo, InMemoryBloggerProfileRepository):
        pytest.skip("Need InMemoryBloggerProfileRepository")
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    blogger_registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001090"),
        external_id="1090",
        username="adv",
    )
    blogger_user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001091"),
        external_id="1091",
        username="blogger",
    )
    now = datetime.now(timezone.utc)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger_user.user_id,
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            city="Moscow",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
        )
    )
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001092"),
        blogger_id=blogger_user.user_id,
        advertiser_id=advertiser.user_id,
        interaction_id=UUID("00000000-0000-0000-0000-000000001093"),
    )

    callback = FakeCallback(
        data=f"feedback_reason:adv:{interaction.interaction_id}:creator_wanted_to_change",
        user=FakeUser(1090),
    )
    state = FakeFSMContext()
    await handle_feedback_reason(
        callback,
        state,
        user_service,
        interaction_service,
        blogger_registration_service,
    )

    assert "Спасибо" in callback.answers[0]
    updated = await interaction_repo.get_by_id(interaction.interaction_id)
    assert updated is not None
    assert "Креатор хотел изменить условия" in (updated.from_advertiser or "")
    profile = await blogger_repo.get_by_user_id(blogger_user.user_id)
    assert profile is not None
    assert profile.wanted_to_change_terms_count == 1


@pytest.mark.asyncio
async def test_feedback_handler_issue_sets_state_and_sends_prompt(
    user_repo, interaction_repo, nps_repo
) -> None:
    """When user selects issue, set FSM state and send prompt for description."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001100"),
        external_id="1100",
        username="adv",
    )
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001102"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001103"),
        advertiser_id=advertiser.user_id,
        interaction_id=UUID("00000000-0000-0000-0000-000000001101"),
    )

    callback = FakeCallback(
        data=f"feedback:adv:{interaction.interaction_id}:issue", user=FakeUser(1100)
    )
    state = FakeFSMContext()
    await handle_feedback(callback, state, user_service, interaction_service, nps_repo)

    assert callback.answers
    assert callback.message.answers
    assert any(
        "проблем" in str(a).lower() or "скриншот" in str(a).lower()
        for a in callback.message.answers
    )
    assert state.state is not None
    updated = await interaction_repo.get_by_id(interaction.interaction_id)
    assert updated is not None
    assert updated.from_advertiser is None


@pytest.mark.asyncio
async def test_handle_feedback_reason_no_data(blogger_repo) -> None:
    """When callback has no data, return without error."""

    from ugc_bot.bot.handlers.feedback import handle_feedback_reason
    from ugc_bot.application.services.blogger_registration_service import (
        BloggerRegistrationService,
    )
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryBloggerProfileRepository,
        InMemoryUserRepository,
        InMemoryInteractionRepository,
    )

    if not isinstance(blogger_repo, InMemoryBloggerProfileRepository):
        pytest.skip("Need InMemoryBloggerProfileRepository")
    user_repo = InMemoryUserRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    blogger_registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    callback = FakeCallback(
        data="feedback_reason:adv:00000000-0000-0000-0000-000000001111:other",
        user=FakeUser(1),
    )
    callback.data = None
    state = FakeFSMContext()
    await handle_feedback_reason(
        callback, state, user_service, interaction_service, blogger_registration_service
    )
    assert not callback.answers


@pytest.mark.asyncio
async def test_handle_feedback_reason_wrong_parts_count(blogger_repo) -> None:
    """Reject callback with wrong number of parts."""

    from ugc_bot.bot.handlers.feedback import handle_feedback_reason
    from ugc_bot.application.services.blogger_registration_service import (
        BloggerRegistrationService,
    )
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryBloggerProfileRepository,
        InMemoryUserRepository,
        InMemoryInteractionRepository,
    )

    if not isinstance(blogger_repo, InMemoryBloggerProfileRepository):
        pytest.skip("Need InMemoryBloggerProfileRepository")
    user_repo = InMemoryUserRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    blogger_registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    callback = FakeCallback(data="feedback_reason:adv:uuid", user=FakeUser(1))
    state = FakeFSMContext()
    await handle_feedback_reason(
        callback, state, user_service, interaction_service, blogger_registration_service
    )
    assert "Неверный формат." in callback.answers


@pytest.mark.asyncio
async def test_handle_feedback_reason_invalid_uuid(
    user_repo, interaction_repo, blogger_repo
) -> None:
    """Reject invalid UUID in feedback_reason callback."""

    from ugc_bot.bot.handlers.feedback import handle_feedback_reason
    from ugc_bot.application.services.blogger_registration_service import (
        BloggerRegistrationService,
    )
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryBloggerProfileRepository,
    )

    if not isinstance(blogger_repo, InMemoryBloggerProfileRepository):
        pytest.skip("Need InMemoryBloggerProfileRepository")
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    blogger_registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    callback = FakeCallback(
        data="feedback_reason:adv:not-a-uuid:terms_differed", user=FakeUser(1)
    )
    state = FakeFSMContext()
    await handle_feedback_reason(
        callback, state, user_service, interaction_service, blogger_registration_service
    )
    assert "Неверный идентификатор." in callback.answers


@pytest.mark.asyncio
async def test_feedback_reason_other_sets_state(
    user_repo, interaction_repo, blogger_repo
) -> None:
    """When user selects no_deal reason 'Другое', set FSM and ask for text."""

    from ugc_bot.bot.handlers.feedback import handle_feedback_reason
    from ugc_bot.application.services.blogger_registration_service import (
        BloggerRegistrationService,
    )
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryBloggerProfileRepository,
    )

    if not isinstance(blogger_repo, InMemoryBloggerProfileRepository):
        pytest.skip("Need InMemoryBloggerProfileRepository")
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    blogger_registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001110"),
        external_id="1110",
        username="blogger",
    )
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001112"),
        blogger_id=blogger.user_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000001113"),
        interaction_id=UUID("00000000-0000-0000-0000-000000001111"),
    )

    callback = FakeCallback(
        data=f"feedback_reason:blog:{interaction.interaction_id}:other",
        user=FakeUser(1110),
    )
    state = FakeFSMContext()
    await handle_feedback_reason(
        callback, state, user_service, interaction_service, blogger_registration_service
    )

    assert callback.message.answers
    assert any("причину" in str(a) for a in callback.message.answers)
    assert state.state is not None
    assert state._data.get("feedback_interaction_id") == str(interaction.interaction_id)
    assert state._data.get("feedback_kind") == "blog"


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_records_feedback(
    user_repo, interaction_repo
) -> None:
    """When user sends text in waiting_no_deal_other, record feedback and clear state."""

    from ugc_bot.bot.handlers.feedback import (
        FeedbackStates,
        handle_no_deal_other_text,
    )

    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001120"),
        external_id="1120",
        username="blogger",
    )
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001122"),
        blogger_id=blogger.user_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000001123"),
        interaction_id=UUID("00000000-0000-0000-0000-000000001121"),
    )

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    state = FakeFSMContext()
    await state.set_state(FeedbackStates.waiting_no_deal_other)
    await state.update_data(
        feedback_interaction_id=str(interaction.interaction_id),
        feedback_kind="blog",
    )
    message = FakeMessage(text="Не устроила оплата", user=FakeUser(1120))

    await handle_no_deal_other_text(message, state, user_service, interaction_service)

    assert state.cleared is True
    assert any("Спасибо" in str(a) for a in message.answers)
    updated = await interaction_repo.get_by_id(interaction.interaction_id)
    assert updated is not None
    assert "Другое" in (updated.from_blogger or "")
    assert "Не устроила оплата" in (updated.from_blogger or "")


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_no_from_user(
    user_repo, interaction_repo
) -> None:
    """When message has no from_user, return without reply."""

    from ugc_bot.bot.handlers.feedback import (
        FeedbackStates,
        handle_no_deal_other_text,
    )

    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001124"),
        external_id="1124",
        username="blogger",
    )
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001125"),
        blogger_id=blogger.user_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000001126"),
        interaction_id=UUID("00000000-0000-0000-0000-000000001127"),
    )
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    state = FakeFSMContext()
    await state.set_state(FeedbackStates.waiting_no_deal_other)
    await state.update_data(
        feedback_interaction_id=str(interaction.interaction_id),
        feedback_kind="blog",
    )
    message = FakeMessage(text="Причина", user=FakeUser(1124))
    message.from_user = None

    await handle_no_deal_other_text(message, state, user_service, interaction_service)

    assert not message.answers


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_empty_asks_again(
    user_repo, interaction_repo
) -> None:
    """When user sends empty text in waiting_no_deal_other, ask again and keep state."""

    from ugc_bot.bot.handlers.feedback import (
        FeedbackStates,
        handle_no_deal_other_text,
    )

    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001125"),
        external_id="1125",
        username="blogger",
    )
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001126"),
        blogger_id=blogger.user_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000001127"),
        interaction_id=UUID("00000000-0000-0000-0000-000000001128"),
    )

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    state = FakeFSMContext()
    await state.set_state(FeedbackStates.waiting_no_deal_other)
    await state.update_data(
        feedback_interaction_id=str(interaction.interaction_id),
        feedback_kind="blog",
    )
    message = FakeMessage(text="   ", user=FakeUser(1125))

    await handle_no_deal_other_text(message, state, user_service, interaction_service)

    assert any("причину" in str(a) or "текстом" in str(a) for a in message.answers)
    updated = await interaction_repo.get_by_id(interaction.interaction_id)
    assert updated is not None
    assert updated.from_blogger is None


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_interaction_not_found(
    user_repo, interaction_repo
) -> None:
    """When interaction is not found in waiting_no_deal_other, reply and clear state."""

    from ugc_bot.bot.handlers.feedback import (
        FeedbackStates,
        handle_no_deal_other_text,
    )

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001129"),
        external_id="1129",
        username="blogger",
    )
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    state = FakeFSMContext()
    await state.set_state(FeedbackStates.waiting_no_deal_other)
    await state.update_data(
        feedback_interaction_id="00000000-0000-0000-0000-000000001199",
        feedback_kind="blog",
    )
    message = FakeMessage(text="Другая причина", user=FakeUser(1129))

    await handle_no_deal_other_text(message, state, user_service, interaction_service)

    assert any("не найдено" in str(a).lower() for a in message.answers)


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_invalid_uuid(
    user_repo, interaction_repo
) -> None:
    """When state has invalid interaction_id UUID, reply error and clear state."""

    from ugc_bot.bot.handlers.feedback import (
        FeedbackStates,
        handle_no_deal_other_text,
    )

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001198"),
        external_id="1198",
        username="blogger",
    )
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    state = FakeFSMContext()
    await state.set_state(FeedbackStates.waiting_no_deal_other)
    await state.update_data(
        feedback_interaction_id="not-a-uuid",
        feedback_kind="blog",
    )
    message = FakeMessage(text="Текст причины", user=FakeUser(1198))

    await handle_no_deal_other_text(message, state, user_service, interaction_service)

    assert any(
        "ошибка" in str(a).lower() or "попробуйте" in str(a).lower()
        for a in message.answers
    )


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_user_not_in_repo_clears_state(
    interaction_repo,
) -> None:
    """When user is not in repo, clear state and return without reply."""

    from ugc_bot.bot.handlers.feedback import (
        FeedbackStates,
        handle_no_deal_other_text,
    )
    from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository

    user_repo = InMemoryUserRepository()
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001200"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001201"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001202"),
        interaction_id=UUID("00000000-0000-0000-0000-000000001203"),
    )
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    state = FakeFSMContext()
    await state.set_state(FeedbackStates.waiting_no_deal_other)
    await state.update_data(
        feedback_interaction_id=str(interaction.interaction_id),
        feedback_kind="blog",
    )
    message = FakeMessage(text="Причина", user=FakeUser(1204))

    await handle_no_deal_other_text(message, state, user_service, interaction_service)

    assert state.cleared is True
    assert not message.answers


@pytest.mark.asyncio
async def test_handle_issue_description_creates_complaint_and_records(
    user_repo, interaction_repo, complaint_repo
) -> None:
    """When user sends text in waiting_issue_description, create complaint and record ISSUE."""

    from ugc_bot.application.services.complaint_service import ComplaintService
    from ugc_bot.bot.handlers.feedback import (
        FeedbackStates,
        handle_issue_description,
    )

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001130"),
        external_id="1130",
        username="adv",
    )
    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001131"),
        external_id="1131",
        username="blogger",
    )
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001132"),
        blogger_id=blogger.user_id,
        advertiser_id=advertiser.user_id,
        interaction_id=UUID("00000000-0000-0000-0000-000000001133"),
    )

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    complaint_service = ComplaintService(complaint_repo=complaint_repo)
    state = FakeFSMContext()
    await state.set_state(FeedbackStates.waiting_issue_description)
    await state.update_data(
        feedback_interaction_id=str(interaction.interaction_id),
        feedback_kind="adv",
    )
    message = FakeMessage(text="Подозреваю мошенничество", user=FakeUser(1130))

    await handle_issue_description(
        message, state, user_service, interaction_service, complaint_service
    )

    assert state.cleared is True
    assert any("заявку" in str(a).lower() for a in message.answers)
    updated = await interaction_repo.get_by_id(interaction.interaction_id)
    assert updated is not None
    assert updated.from_advertiser == "⚠️ Проблема / подозрение на мошенничество"
    assert updated.status == InteractionStatus.ISSUE


@pytest.mark.asyncio
async def test_handle_issue_description_expired_state(
    user_repo, interaction_repo, complaint_repo
) -> None:
    """When state data is missing (expired), reply session expired and clear state."""

    from ugc_bot.application.services.complaint_service import ComplaintService
    from ugc_bot.bot.handlers.feedback import (
        FeedbackStates,
        handle_issue_description,
    )

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001135"),
        external_id="1135",
        username="adv",
    )
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    complaint_service = ComplaintService(complaint_repo=complaint_repo)
    state = FakeFSMContext()
    await state.set_state(FeedbackStates.waiting_issue_description)
    await state.update_data(
        feedback_interaction_id="00000000-0000-0000-0000-000000001139",
        feedback_kind="invalid_kind",
    )
    message = FakeMessage(text="Проблема", user=FakeUser(1135))

    await handle_issue_description(
        message, state, user_service, interaction_service, complaint_service
    )

    assert state.cleared is True
    assert any("истекла" in str(a).lower() for a in message.answers)


@pytest.mark.asyncio
async def test_handle_issue_description_interaction_not_found(
    user_repo, interaction_repo, complaint_repo
) -> None:
    """When interaction is not found (valid UUID), reply and clear state."""

    from ugc_bot.application.services.complaint_service import ComplaintService
    from ugc_bot.bot.handlers.feedback import (
        FeedbackStates,
        handle_issue_description,
    )

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001136"),
        external_id="1136",
        username="adv",
    )
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000001137"),
        external_id="1137",
        username="blogger",
    )
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    complaint_service = ComplaintService(complaint_repo=complaint_repo)
    state = FakeFSMContext()
    await state.set_state(FeedbackStates.waiting_issue_description)
    await state.update_data(
        feedback_interaction_id="00000000-0000-0000-0000-000000001140",
        feedback_kind="adv",
    )
    message = FakeMessage(text="Проблема", user=FakeUser(1136))

    await handle_issue_description(
        message, state, user_service, interaction_service, complaint_service
    )

    assert state.cleared is True
    assert any("не найдено" in str(a).lower() for a in message.answers)


@pytest.mark.asyncio
async def test_handle_issue_description_user_not_in_repo_clears_state(
    interaction_repo, complaint_repo
) -> None:
    """When user is not in repo in waiting_issue_description, clear state and return."""

    from ugc_bot.application.services.complaint_service import ComplaintService
    from ugc_bot.bot.handlers.feedback import (
        FeedbackStates,
        handle_issue_description,
    )
    from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository

    user_repo = InMemoryUserRepository()
    interaction = await create_test_interaction(
        interaction_repo,
        order_id=UUID("00000000-0000-0000-0000-000000001141"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001142"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001143"),
        interaction_id=UUID("00000000-0000-0000-0000-000000001144"),
    )
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    complaint_service = ComplaintService(complaint_repo=complaint_repo)
    state = FakeFSMContext()
    await state.set_state(FeedbackStates.waiting_issue_description)
    await state.update_data(
        feedback_interaction_id=str(interaction.interaction_id),
        feedback_kind="adv",
    )
    message = FakeMessage(text="Проблема", user=FakeUser(1145))

    await handle_issue_description(
        message, state, user_service, interaction_service, complaint_service
    )

    assert state.cleared is True
    assert not message.answers
