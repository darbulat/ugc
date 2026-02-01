"""Tests for feedback handler."""

import pytest
from uuid import UUID

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.feedback import handle_feedback
from ugc_bot.domain.enums import AudienceGender, InteractionStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryNpsRepository
from tests.helpers.fakes import FakeCallback, FakeUser
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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)

    assert callback.answers
    updated = await interaction_repo.get_by_id(interaction.interaction_id)
    assert updated is not None
    assert updated.from_advertiser == "✅ Сделка состоялась"


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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)
    assert "Недостаточно прав." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_invalid_format(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Reject malformed callback data."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    callback = FakeCallback(data="feedback:bad", user=FakeUser(1))
    await handle_feedback(callback, user_service, interaction_service, nps_repo)
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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)
    assert "Неверный статус." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_invalid_uuid(
    user_repo, interaction_repo, nps_repo
) -> None:
    """Reject invalid UUID values."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    callback = FakeCallback(data="feedback:adv:not-a-uuid:ok", user=FakeUser(1))
    await handle_feedback(callback, user_service, interaction_service, nps_repo)
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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)
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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)
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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)
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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)
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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)

    assert callback.answers
    updated = await interaction_repo.get_by_id(interaction.interaction_id)
    assert updated is not None
    assert updated.from_blogger == "✅ Сделка состоялась"


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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)

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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)

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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)

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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)

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
    await handle_feedback_reason(
        callback,
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
async def test_feedback_handler_issue_sends_message(
    user_repo, interaction_repo, nps_repo
) -> None:
    """When user selects issue, record and send message about support."""

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
    await handle_feedback(callback, user_service, interaction_service, nps_repo)

    assert callback.answers
    assert callback.message.answers
    assert any(
        "проблем" in str(a).lower() or "поддерж" in str(a).lower()
        for a in callback.message.answers
    )
