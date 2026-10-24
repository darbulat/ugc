"""Real aggregate service over explicitly synthetic authority/transactions."""

from dataclasses import replace
from uuid import uuid4, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.social_editor import editor_fixture
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.enums import UserStatus, WorkFormat
from ugc_bot.infrastructure.db.repositories.social import (
    SqlAlchemySocialAccountRepository,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_editor_saves_lists_prompts_and_removes_in_one_transaction(
    platform,
):
    editor, user, principal = await editor_fixture(platform=platform)
    service = editor.service()
    saved = await service.save_editor_account(
        user.user_id,
        "tiktok",
        "https://tiktok.com/@Creator",
        principal=principal,
    )
    assert saved.account.handle == "creator"
    assert saved.account.verified is False
    assert saved.account.followers_count is None
    assert saved.next_platform == "youtube"
    assert editor.starts == editor.commits == 1
    assert editor.events.index("authority") < editor.events.index("save")
    state = await service.editor_state(user.user_id, principal=principal)
    assert [a.platform for a in state.accounts] == ["instagram", "tiktok"]
    assert state.next_platform == "youtube"
    assert editor.starts == 2
    repeated = await service.save_editor_account(
        user.user_id,
        "tiktok",
        "https://tiktok.com/@Second",
        principal=principal,
        work_format=WorkFormat.ADS_IN_ACCOUNT,
    )
    assert repeated.account.account_id == saved.account.account_id
    assert repeated.account.created_at == saved.account.created_at
    assert repeated.account.work_format == "ads_in_account"
    omitted = await service.save_editor_account(
        user.user_id, "tiktok", "https://tiktok.com/@Third", principal=principal
    )
    assert omitted.account.work_format == "ads_in_account"
    assert (
        await service.remove_editor_account(
            user.user_id, saved.account.account_id, principal=principal
        )
        is True
    )
    assert (
        await service.remove_editor_account(
            user.user_id, saved.account.account_id, principal=principal
        )
        is False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile,confirmed", [(False, False), (True, False), (True, True)]
)
async def test_existing_profile_and_prompt_compatibility(profile, confirmed):
    editor, user, principal = await editor_fixture(
        profile=profile, confirmed=confirmed
    )
    service = editor.service()
    state = await service.editor_state(user.user_id, principal=principal)
    assert len(state.accounts) == int(profile)
    assert state.next_platform == ("tiktok" if confirmed else "instagram")
    if not confirmed:
        code = (
            "social_instagram_verification_required"
            if profile
            else "social_creator_profile_required"
        )
        with pytest.raises(ValueError, match=code):
            await service.save_editor_account(
                user.user_id,
                "youtube",
                "https://youtube.com/@creator",
                principal=principal,
            )
    else:
        assert state.accounts[0].external_id is None
        assert (
            await service.editor_state(
                user.user_id, principal=principal, skipped=["tiktok", "youtube"]
            )
        ).next_platform == "telegram"


@pytest.mark.asyncio
async def test_post_save_source_or_result_failure_rolls_back(monkeypatch):
    editor, user, principal = await editor_fixture()
    service = editor.service()
    editor.fail_post_save = True
    with pytest.raises(RuntimeError, match="post-save"):
        await service.save_editor_account(
            user.user_id,
            "youtube",
            "https://youtube.com/@creator",
            principal=principal,
        )
    assert editor.storage.accounts == {} and editor.rollbacks == 1
    editor.fail_post_save = False
    import ugc_bot.application.services.social_account_service as module

    def invalid_result(*args, **kwargs):
        raise ValueError("synthetic invalid detached saved result")

    monkeypatch.setattr(module, "SocialEditorSaved", invalid_result)
    with pytest.raises(ValueError, match="invalid detached"):
        await service.save_editor_account(
            user.user_id,
            "youtube",
            "https://youtube.com/@creator",
            principal=principal,
        )
    assert editor.storage.accounts == {} and editor.rollbacks == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", list(UserStatus))
async def test_current_status_is_checked_before_private_facts(status):
    editor, user, principal = await editor_fixture()
    await editor.users.save(replace(user, status=status))
    service = editor.service()
    if status in {
        UserStatus.BLOCKED,
        UserStatus.BOT_BLOCKED,
        UserStatus.DELETED,
    }:
        with pytest.raises(ValueError, match="social_account_unavailable"):
            await service.editor_state(user.user_id, principal=principal)
        assert "facts" not in editor.events
    else:
        assert (
            await service.editor_state(user.user_id, principal=principal)
        ).next_platform == "tiktok"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["read", "save", "remove"])
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_current_native_denies_before_private_or_mutation(
    operation, platform
):
    editor, user, principal = await editor_fixture(platform=platform)
    await editor.users.save(
        replace(
            user,
            **{"telegram_id" if platform == "telegram" else "max_id": None},
        )
    )
    service = editor.service()
    with pytest.raises(ValueError, match="financial_principal_changed"):
        if operation == "read":
            await service.editor_state(user.user_id, principal=principal)
        elif operation == "save":
            await service.save_editor_account(
                user.user_id,
                "youtube",
                "https://youtube.com/@creator",
                principal=principal,
            )
        else:
            await service.remove_editor_account(
                user.user_id, uuid4(), principal=principal
            )
    assert "facts" not in editor.events and "save" not in editor.events


@pytest.mark.asyncio
@pytest.mark.parametrize("proof", [None, uuid4()])
async def test_service_rejects_missing_or_uuid_proof_without_transaction(proof):
    editor, user, _ = await editor_fixture()
    with pytest.raises(ValueError, match="financial_principal_changed"):
        await editor.service().editor_state(user.user_id, principal=proof)
    assert editor.starts == 0


@pytest.mark.asyncio
async def test_wrong_owner_or_capability_refused_before_source():
    editor, user, principal = await editor_fixture()
    service = editor.service()
    with pytest.raises(ValueError, match="financial_principal_changed"):
        await service.editor_state(uuid4(), principal=principal)
    service.editor_repository = None
    with pytest.raises(ValueError, match="social_unavailable"):
        await service.editor_state(user.user_id, principal=principal)
    service.editor_repository = object()
    with pytest.raises(ValueError, match="social_unavailable"):
        await service.editor_state(user.user_id, principal=principal)
    service.editor_repository = editor
    service.transaction_manager = None
    with pytest.raises(ValueError, match="social_unavailable"):
        await service.editor_state(user.user_id, principal=principal)
    assert editor.starts == 0
    editor.wrong_facts = True
    with pytest.raises(ValueError, match="social_unavailable"):
        await editor.service().editor_state(user.user_id, principal=principal)


@pytest.mark.asyncio
async def test_foreign_and_instagram_remove_do_not_gain_new_rules():
    editor, user, principal = await editor_fixture()
    service = editor.service()
    account = await service.save_editor_account(
        user.user_id, "telegram", "https://t.me/creator", principal=principal
    )
    profile = await editor.profiles.get_by_user_id(user.user_id)
    await editor.profiles.save(replace(profile, confirmed=False))
    assert await service.remove_editor_account(
        user.user_id, account.account.account_id, principal=principal
    )
    with pytest.raises(
        ValueError, match="social_instagram_verification_required"
    ):
        await service.remove_editor_account(
            user.user_id, uuid5(user.user_id, "instagram"), principal=principal
        )
    foreign = replace(account.account, account_id=uuid4(), user_id=uuid4())
    await editor.storage.save(foreign)
    with pytest.raises(ValueError, match="social_account_owner_mismatch"):
        await service.remove_editor_account(
            user.user_id, foreign.account_id, principal=principal
        )
    assert await editor.storage.get_by_id(foreign.account_id) == foreign


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["read_editor", "prepare_editor_write"])
async def test_sql_unbound_or_unknown_session_refuses_without_engine(method):
    repo = SqlAlchemySocialAccountRepository(async_sessionmaker())
    user = uuid4()
    principal = AuthenticatedMessengerPrincipal(user, "telegram", "101")
    for session in (None, object(), AsyncSession()):
        try:
            with pytest.raises(ValueError, match="social_unavailable"):
                await getattr(repo, method)(
                    user, principal=principal, session=session
                )
        finally:
            if isinstance(session, AsyncSession):
                await session.close()


@pytest.mark.asyncio
async def test_remove_invalid_detached_result_rolls_back(monkeypatch):
    editor, user, principal = await editor_fixture()
    service = editor.service()
    saved = await service.save_editor_account(
        user.user_id, "telegram", "https://t.me/creator", principal=principal
    )
    original = editor.remove

    async def broken_remove(*args, **kwargs):
        await original(*args, **kwargs)
        return object()

    monkeypatch.setattr(editor, "remove", broken_remove)
    with pytest.raises(ValueError, match="social_unavailable"):
        await service.remove_editor_account(
            user.user_id, saved.account.account_id, principal=principal
        )
    assert (
        await editor.storage.get_by_id(saved.account.account_id)
        == saved.account
    )


@pytest.mark.asyncio
async def test_all_added_platforms_and_optional_vk_have_one_prompt_set():
    editor, user, principal = await editor_fixture()
    service = editor.service()
    for platform, url, following in (
        ("tiktok", "https://tiktok.com/@creator", "youtube"),
        ("youtube", "https://youtube.com/@creator", "telegram"),
        ("telegram", "https://t.me/creator", None),
    ):
        saved = await service.save_editor_account(
            user.user_id, platform, url, principal=principal
        )
        assert saved.next_platform == following
    assert (
        await service.editor_state(
            user.user_id, principal=principal, include_vk=True
        )
    ).next_platform == "vk"
    await service.save_editor_account(
        user.user_id, "vk", "https://vk.com/creator", principal=principal
    )
    state = await service.editor_state(
        user.user_id, principal=principal, include_vk=True
    )
    assert [a.platform for a in state.accounts] == [
        "instagram",
        "tiktok",
        "youtube",
        "telegram",
        "vk",
    ]
    assert state.next_platform is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "network,url,code",
    [
        (
            "instagram",
            "https://instagram.com/creator",
            "social_instagram_verification_required",
        ),
        (
            "youtube",
            "https://youtube.com/watch?v=PRIVATE",
            "social_profile_url_invalid",
        ),
    ],
)
async def test_editor_normalization_refusal_is_inside_authority(
    network, url, code
):
    editor, user, principal = await editor_fixture()
    with pytest.raises(ValueError, match=code):
        await editor.service().save_editor_account(
            user.user_id, network, url, principal=principal
        )
    assert editor.events.index("authority") < editor.events.index("facts")
    assert editor.storage.accounts == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "nested,pending", [(False, False), (True, False), (False, True)]
)
async def test_actual_unbound_active_session_metadata_never_executes(
    nested, pending
):
    from ugc_bot.infrastructure.db.models import UserModel

    repo = SqlAlchemySocialAccountRepository(async_sessionmaker())
    async with AsyncSession() as session, session.begin():
        if pending:
            session.add(UserModel(user_id=uuid4()))
        if nested:
            async with session.begin_nested():
                with pytest.raises(ValueError, match="social_unavailable"):
                    repo._editor_session(session)
        else:
            with pytest.raises(ValueError, match="social_unavailable"):
                repo._editor_session(session)
        # No flush/connection was requested. Discard pending test objects.
        session.expunge_all()
