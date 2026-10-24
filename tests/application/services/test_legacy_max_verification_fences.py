"""Separate MAX owners remain separate after proven Instagram confirmation."""

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from tests.application.services.test_instagram_verification_service import (
    _seed_profile,
    _seed_user,
)
from tests.helpers.legacy_verification import MemoryVerificationTransaction
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInstagramVerificationRepository,
    InMemoryUserRepository,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("other_telegram", [None, "original-tg"])
async def test_separate_max_owner_is_not_detached_by_verification(
    other_telegram,
):
    users = InMemoryUserRepository()
    profiles = InMemoryBloggerProfileRepository()
    codes = InMemoryInstagramVerificationRepository()
    target = await _seed_user(users)
    await _seed_profile(profiles, target)
    owner = User(
        user_id=uuid4(),
        messenger_type=MessengerType.MAX,
        username="Original MAX owner",
        status=UserStatus.ACTIVE,
        issue_count=7,
        created_at=datetime.now(timezone.utc),
        telegram_id=other_telegram,
        max_id="max-owner",
        max_chat_id="original-chat",
        admin=True,
        country="kz",
        language="kk",
    )
    await users.save(owner)
    before = await users.get_by_id(target)
    service = InstagramVerificationService(
        users,
        profiles,
        codes,
        transaction_manager=MemoryVerificationTransaction(
            users, profiles, codes
        ),
        user_role_service=UserRoleService(users, blogger_profile_repo=profiles),
    )
    code = await service.generate_code(
        target, link_max_id=owner.max_id, link_max_chat_id="initiating-chat"
    )
    result = await service.verify_code(target, code.code)
    assert result.__class__.__name__ == "VerificationLinkConflict"
    assert await users.get_by_id(owner.user_id) == owner
    assert await users.get_by_id(target) == before
    assert (await profiles.get_by_user_id(target)).confirmed
    assert codes.codes[code.code_id].used


async def environment(*, api=True, linking=True, social=False):
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryInstagramGraphApiClient,
    )
    from ugc_bot.infrastructure.memory_social import (
        InMemorySocialAccountRepository,
    )

    users = InMemoryUserRepository()
    profiles = InMemoryBloggerProfileRepository()
    codes = InMemoryInstagramVerificationRepository()
    target = await _seed_user(users)
    await _seed_profile(profiles, target)
    accounts = InMemorySocialAccountRepository() if social else None
    tx = MemoryVerificationTransaction(users, profiles, codes, accounts)
    verifier = InstagramVerificationService(
        users,
        profiles,
        codes,
        InMemoryInstagramGraphApiClient(username_map={"sender": "test_user"})
        if api
        else None,
        transaction_manager=tx,
        user_role_service=UserRoleService(users, blogger_profile_repo=profiles)
        if linking
        else None,
        social_repo=accounts,
    )
    return users, profiles, codes, target, verifier, accounts


@pytest_asyncio.fixture
async def sql_legacy_lifetime(monkeypatch):
    """Real unconnected transaction lifetimes, synthetic SQL boundaries."""
    from types import SimpleNamespace

    from sqlalchemy.ext.asyncio import AsyncSession

    from ugc_bot.infrastructure.db.repositories import messenger_linking
    from ugc_bot.infrastructure.db.repositories.user import (
        SqlAlchemyUserRepository,
        _to_user_model,
    )

    target = User(
        user_id=uuid4(),
        messenger_type=MessengerType.TELEGRAM,
        username="target",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        telegram_id="target-tg",
    )
    state = {"target": target}
    reads, writes = [], []

    async def read(self, db, condition, *, lock=False):
        reads.append((condition.left.name, lock))
        return None if condition.left.name == "max_id" else state["target"]

    async def native_barrier(db):
        reads.append(("native_barrier", True))

    async def write(query):
        writes.append(query)
        state["target"] = replace(
            target, max_id="new-max", max_chat_id="recorded-chat"
        )
        return _to_user_model(state["target"])

    monkeypatch.setattr(SqlAlchemyUserRepository, "_legacy_user", read)
    monkeypatch.setattr(
        messenger_linking, "acquire_link_identity_barrier", native_barrier
    )
    async with AsyncSession() as session:
        monkeypatch.setattr(session, "scalar", write)
        await session.begin()
        yield SimpleNamespace(
            repo=SqlAlchemyUserRepository(None),
            session=session,
            target=target,
            reads=reads,
            writes=writes,
        )


async def prepare_sql_lifetime(boundary):
    return await boundary.repo.prepare_legacy_max_attachment(
        boundary.target.user_id,
        code_id=uuid4(),
        max_id="new-max",
        max_chat_id="recorded-chat",
        session=boundary.session,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["commit", "rollback"])
async def test_sql_preparation_expires_when_root_transaction_ends(
    sql_legacy_lifetime, ending
):
    boundary = sql_legacy_lifetime
    preparation = await prepare_sql_lifetime(boundary)
    assert preparation.protected
    root = boundary.session.get_transaction()
    await getattr(root, ending)()
    assert not root.is_active
    await boundary.session.begin()
    boundary.reads.clear()
    result = await boundary.repo.attach_prepared_max(
        preparation, session=boundary.session
    )
    assert result.state == "unavailable"
    assert boundary.reads == []
    assert boundary.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["commit", "rollback"])
async def test_sql_preparation_refuses_an_enclosing_savepoint(
    sql_legacy_lifetime, ending
):
    boundary = sql_legacy_lifetime
    root = boundary.session.get_transaction()
    nested = await boundary.session.begin_nested()
    preparation = await prepare_sql_lifetime(boundary)
    await getattr(nested, ending)()
    assert root.is_active
    result = await boundary.repo.attach_prepared_max(
        preparation, session=boundary.session
    )
    assert not preparation.protected
    assert preparation.reason == "nested_transaction_unavailable"
    assert result.state == "unavailable"
    assert boundary.reads == []
    assert boundary.writes == []


@pytest.mark.asyncio
async def test_sql_preparation_rejects_another_active_session(
    sql_legacy_lifetime,
):
    from sqlalchemy.ext.asyncio import AsyncSession

    boundary = sql_legacy_lifetime
    preparation = await prepare_sql_lifetime(boundary)
    boundary.reads.clear()
    async with AsyncSession() as other:
        await other.begin()
        result = await boundary.repo.attach_prepared_max(
            preparation, session=other
        )
    assert result.state == "unavailable"
    assert boundary.reads == []
    assert boundary.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("intervening", [None, "commit", "rollback"])
async def test_root_preparation_survives_later_attachment_savepoint(
    sql_legacy_lifetime, intervening
):
    boundary = sql_legacy_lifetime
    preparation = await prepare_sql_lifetime(boundary)
    frozen = (
        preparation.target_id,
        preparation.code_id,
        preparation.max_id,
        preparation.max_chat_id,
    )
    root = boundary.session.get_transaction()
    if intervening is not None:
        nested = await boundary.session.begin_nested()
        await getattr(nested, intervening)()
    result = await boundary.repo.attach_prepared_max(
        preparation, session=boundary.session
    )
    assert result.state == "ready"
    assert result.reason == "attached"
    assert len(boundary.writes) == 1
    assert root.is_active
    assert boundary.session.get_transaction() is root
    # Ending the attachment's own savepoint cannot expire the root capability.
    result = await boundary.repo.attach_prepared_max(
        preparation, session=boundary.session
    )
    assert result.state == "same_account"
    assert len(boundary.writes) == 1
    assert frozen == (
        preparation.target_id,
        preparation.code_id,
        preparation.max_id,
        preparation.max_chat_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_sql_preparation_requires_the_registered_immutable_object(
    sql_legacy_lifetime, changed
):
    boundary = sql_legacy_lifetime
    preparation = await prepare_sql_lifetime(boundary)
    copied = replace(
        preparation, max_id="another-max" if changed else preparation.max_id
    )
    boundary.reads.clear()
    result = await boundary.repo.attach_prepared_max(
        copied, session=boundary.session
    )
    assert result.state == "unavailable"
    assert boundary.reads == []
    assert boundary.writes == []


@pytest.mark.asyncio
async def test_sql_registration_cleanup_and_listener_are_bounded(
    sql_legacy_lifetime,
):
    boundary = sql_legacy_lifetime
    first = await prepare_sql_lifetime(boundary)
    second = await prepare_sql_lifetime(boundary)
    assert first is not second
    handlers = boundary.session.sync_session.dispatch.after_transaction_end
    assert len(handlers) == 1
    await boundary.session.commit()
    assert "legacy_max_preparations" not in boundary.session.info
    await boundary.session.begin()
    current = await prepare_sql_lifetime(boundary)
    assert len(handlers) == 1
    boundary.reads.clear()
    expired = await boundary.repo.attach_prepared_max(
        second, session=boundary.session
    )
    assert expired.state == "unavailable"
    assert boundary.reads == []
    accepted = await boundary.repo.attach_prepared_max(
        current, session=boundary.session
    )
    assert accepted.state == "ready"
    assert len(boundary.writes) == 1


@pytest.mark.asyncio
async def test_code_expiring_during_current_profile_wait_is_not_consumed(
    monkeypatch,
):
    import asyncio
    from datetime import timedelta

    users, profiles, codes, target, verifier, _ = await environment()
    code = await verifier.generate_code(target)
    codes.codes[code.code_id] = replace(
        code, expires_at=datetime.now(timezone.utc) + timedelta(milliseconds=20)
    )
    original = profiles.current_legacy_profile

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.04)
        return await original(*args, **kwargs)

    monkeypatch.setattr(profiles, "current_legacy_profile", slow)
    result = await verifier.verify_code(target, code.code)
    assert result is False
    assert not codes.codes[code.code_id].used
    assert not profiles.profiles[target].confirmed


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
@pytest.mark.parametrize(
    "failure",
    ["target", "profile", "code_used", "code_owner", "code_id", "native_scope"],
)
async def test_changed_prepared_facts_never_confirm_or_consume(
    monkeypatch, mode, failure
):
    from ugc_bot.application.services.instagram_verification_service import (
        VerificationUnavailable,
    )

    users, profiles, codes, target, verifier, _ = await environment()
    code = await verifier.generate_code(
        target, link_max_id="new-max", link_max_chat_id="recorded-chat"
    )
    original = users.prepare_legacy_max_attachment

    async def changed(*args, **kwargs):
        if failure == "target":
            users.users.pop(target)
        preparation = await original(*args, **kwargs)
        if failure == "profile":
            profiles.profiles.pop(target)
        elif failure == "code_used":
            codes.codes[code.code_id] = replace(code, used=True)
        elif failure == "code_owner":
            codes.codes[code.code_id] = replace(code, user_id=uuid4())
        elif failure == "code_id":
            codes.codes.pop(code.code_id)
            replacement = replace(code, code_id=uuid4())
            codes.codes[replacement.code_id] = replacement
        elif failure == "native_scope":
            codes.codes[code.code_id] = replace(code, link_max_id="another-max")
        return preparation

    monkeypatch.setattr(users, "prepare_legacy_max_attachment", changed)
    result = (
        await verifier.verify_code(target, code.code)
        if mode == "manual"
        else await verifier.verify_code_by_instagram_sender(
            "sender", code.code, "admin"
        )
    )
    assert (
        result is False
        or result is None
        or isinstance(result, VerificationUnavailable)
    )
    if target in profiles.profiles:
        assert not profiles.profiles[target].confirmed
    assert any(item.used for item in codes.codes.values()) is (
        failure == "code_used"
    )
    assert all(user.max_id is None for user in users.users.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
@pytest.mark.parametrize("unsupported", ["none", "fake", "mixed", "default"])
async def test_unsupported_transaction_or_default_preparation_is_unavailable(
    monkeypatch, mode, unsupported, fake_tm
):
    from ugc_bot.application.ports import UserRepository
    from ugc_bot.application.services.instagram_verification_service import (
        VerificationUnavailable,
    )

    users, profiles, codes, target, verifier, _ = await environment()
    code = await verifier.generate_code(target)
    if unsupported == "none":
        verifier.transaction_manager = None
    elif unsupported == "fake":
        verifier.transaction_manager = fake_tm
    elif unsupported == "mixed":
        verifier.social_repo = object()
    else:

        async def default(*args, **kwargs):
            return await UserRepository.prepare_legacy_max_attachment(
                users, *args, **kwargs
            )

        monkeypatch.setattr(users, "prepare_legacy_max_attachment", default)
    result = (
        await verifier.verify_code(target, code.code)
        if mode == "manual"
        else await verifier.verify_code_by_instagram_sender(
            "sender", code.code, "admin"
        )
    )
    assert isinstance(result, VerificationUnavailable)
    assert not codes.codes[code.code_id].used
    assert not profiles.profiles[target].confirmed


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
async def test_supplied_redis_code_adapter_cannot_partially_confirm(mode):
    from ugc_bot.application.services.instagram_verification_service import (
        VerificationUnavailable,
    )
    from ugc_bot.infrastructure.redis_verification import (
        RedisInstagramVerificationRepository,
        _serialize,
    )

    users, profiles, codes, target, verifier, accounts = await environment(
        social=True
    )
    code = await verifier.generate_code(
        target, link_max_id="new-max", link_max_chat_id="recorded-chat"
    )
    before_user = users.users[target]
    before_profile = profiles.profiles[target]

    class SyntheticRedis:
        def __init__(self):
            self.payload = _serialize(code)
            self.reads = 0
            self.writes = 0

        async def get(self, key):
            self.reads += 1
            return self.payload

        async def eval(self, *args):
            self.writes += 1
            raise AssertionError("mixed adapter must not consume Redis code")

    cache = SyntheticRedis()
    redis_codes = RedisInstagramVerificationRepository(
        "redis://synthetic.invalid/0"
    )
    redis_codes._redis = cache
    verifier.verification_repo = redis_codes
    result = (
        await verifier.verify_code(target, code.code)
        if mode == "manual"
        else await verifier.verify_code_by_instagram_sender(
            "sender", code.code, "admin"
        )
    )
    assert isinstance(result, VerificationUnavailable)
    assert result.reason == "transaction_unavailable"
    assert cache.reads == 1
    assert cache.writes == 0
    assert cache.payload == _serialize(code)
    assert users.users[target] == before_user
    assert profiles.profiles[target] == before_profile
    assert codes.codes[code.code_id] == code
    assert accounts.accounts == {}
    with pytest.raises(
        TypeError, match="explicit_memory_verification_adapters_required"
    ):
        MemoryVerificationTransaction(users, profiles, redis_codes)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "no_client",
        "none",
        "blank_actual",
        "blank_expected",
        "username_only",
        "exception",
    ],
)
async def test_missing_external_profile_proof_has_no_confirmation_writes(
    failure,
):
    from ugc_bot.application.ports import InstagramProfileInfo
    from ugc_bot.application.services.instagram_verification_service import (
        VerificationApiUnavailable,
    )
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryInstagramGraphApiClient,
    )

    users, profiles, codes, target, verifier, accounts = await environment(
        social=True
    )
    code = await verifier.generate_code(
        target, link_max_id="new-max", link_max_chat_id="recorded-chat"
    )
    if failure == "no_client":
        verifier.instagram_api_client = None
    elif failure == "none":
        verifier.instagram_api_client = InMemoryInstagramGraphApiClient()
    elif failure == "blank_actual":
        verifier.instagram_api_client.profile_map["sender"] = (
            InstagramProfileInfo(" ")
        )
    elif failure == "blank_expected":
        profiles.profiles[target] = replace(
            profiles.profiles[target], instagram_url="https://instagram.com/"
        )
    else:

        class Client:
            async def get_profile_by_id(self, sender):
                if failure == "exception":
                    raise RuntimeError("Synthetic unavailable provider")
                return

            async def get_username_by_id(self, sender):
                return "test_user"

        verifier.instagram_api_client = Client()
    result = await verifier.verify_code_by_instagram_sender(
        "sender", code.code, "admin"
    )
    assert isinstance(result, VerificationApiUnavailable)
    assert not codes.codes[code.code_id].used
    assert not profiles.profiles[target].confirmed
    assert not accounts.accounts
    assert users.users[target].max_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
@pytest.mark.parametrize(
    "kind", ["unused", "same", "conflict", "missing_service"]
)
async def test_linking_outcome_and_one_time_code_are_explicit(mode, kind):
    from ugc_bot.application.services.instagram_verification_service import (
        VerificationLinkConflict,
        VerificationLinkSuccess,
        VerificationLinkUnavailable,
    )

    users, profiles, codes, target, verifier, _ = await environment(
        linking=kind != "missing_service"
    )
    original = users.users[target]
    if kind == "same":
        users.users[target] = replace(
            original,
            max_id="requested",
            max_chat_id="original-chat",
            username="Original name",
        )
        users.max_index["requested"] = target
    elif kind == "conflict":
        owner = replace(
            original,
            user_id=uuid4(),
            telegram_id=None,
            max_id="requested",
            max_chat_id="owner-chat",
            admin=True,
            language="en",
        )
        await users.save(owner)
    before = dict(users.users)
    code = await verifier.generate_code(
        target,
        link_max_id="requested",
        link_max_chat_id="recorded-chat",
        link_username="Untrusted new name",
        link_phone="+79001234567",
    )
    result = (
        await verifier.verify_code(target, code.code)
        if mode == "manual"
        else await verifier.verify_code_by_instagram_sender(
            "sender", code.code, "admin"
        )
    )
    assert (
        codes.codes[code.code_id].used and profiles.profiles[target].confirmed
    )
    if kind == "unused":
        assert isinstance(result, VerificationLinkSuccess)
        assert users.users[target] == replace(
            original, max_id="requested", max_chat_id="recorded-chat"
        )
        assert profiles.profiles[target].phone == "+79001234567"
    elif kind == "same":
        assert isinstance(result, VerificationLinkSuccess)
        assert users.users == before
        assert not profiles.profiles[target].phone
    elif kind == "conflict":
        assert isinstance(result, VerificationLinkConflict)
        assert result.locale == "en" and result.max_chat_id == "recorded-chat"
        assert users.users == before
        assert not profiles.profiles[target].phone
    else:
        assert isinstance(result, VerificationLinkUnavailable)
        assert result.reason == "linking_service_missing"
        assert users.users == before
        assert not profiles.profiles[target].phone
    assert await verifier.verify_code(target, code.code) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["attach", "social", "consume"])
async def test_unexpected_post_confirmation_failure_rolls_back_all_memory_facts(
    monkeypatch, stage
):
    users, profiles, codes, target, verifier, accounts = await environment(
        social=True
    )
    code = await verifier.generate_code(
        target, link_max_id="new-max", link_max_chat_id="recorded-chat"
    )
    original_profile = profiles.profiles[target]
    history = profiles.identity_history
    before_observations = history.identity_observations

    async def broken(*args, **kwargs):
        raise RuntimeError("Synthetic post-confirmation failure")

    if stage == "attach":
        monkeypatch.setattr(
            type(verifier.user_role_service), "attach_verified_max", broken
        )
    elif stage == "social":
        monkeypatch.setattr(accounts, "save", broken)
    else:
        monkeypatch.setattr(codes, "mark_used", broken)
    with pytest.raises(RuntimeError, match="Synthetic post-confirmation"):
        await verifier.verify_code_by_instagram_sender(
            "sender", code.code, "admin"
        )
    assert profiles.profiles[target] == original_profile
    assert not codes.codes[code.code_id].used
    assert not accounts.accounts
    assert users.users[target].max_id is None and not users.max_index
    assert history.identity_observations == before_observations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"link_max_id": ""},
        {"link_max_id": "bad/native"},
        {"link_max_id": "new-max", "link_max_chat_id": "bad chat"},
        {"link_max_chat_id": "recorded-chat"},
    ],
)
async def test_invalid_recorded_link_metadata_keeps_confirmed_result_explicit(
    metadata,
):
    from ugc_bot.application.services.instagram_verification_service import (
        VerificationLinkUnavailable,
    )

    users, profiles, codes, target, verifier, _ = await environment()
    code = await verifier.generate_code(target, **metadata)
    result = await verifier.verify_code(target, code.code)
    assert isinstance(result, VerificationLinkUnavailable)
    assert (
        codes.codes[code.code_id].used and profiles.profiles[target].confirmed
    )
    assert users.users[target].max_id is None


@pytest.mark.asyncio
async def test_current_expected_username_is_rechecked_after_preparation(
    monkeypatch,
):
    from ugc_bot.application.services.instagram_verification_service import (
        VerificationMismatch,
    )

    users, profiles, codes, target, verifier, _ = await environment()
    code = await verifier.generate_code(target)
    original = users.prepare_legacy_max_attachment

    async def changed(*args, **kwargs):
        preparation = await original(*args, **kwargs)
        profiles.profiles[target] = replace(
            profiles.profiles[target],
            instagram_url="https://instagram.com/renamed",
        )
        return preparation

    monkeypatch.setattr(users, "prepare_legacy_max_attachment", changed)
    result = await verifier.verify_code_by_instagram_sender(
        "sender", code.code, "admin"
    )
    assert isinstance(result, VerificationMismatch)
    assert (
        not profiles.profiles[target].confirmed
        and not codes.codes[code.code_id].used
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phone", ["", "     ", "(((()", "11111", "+79001234567"]
)
async def test_phone_enrichment_requires_valid_metadata_and_fresh_empty_profile(
    phone, monkeypatch
):
    users, profiles, codes, target, verifier, _ = await environment()
    code = await verifier.generate_code(
        target, link_max_id="new-max", link_phone=phone
    )
    original = users.prepare_legacy_max_attachment

    async def changed(*args, **kwargs):
        preparation = await original(*args, **kwargs)
        profiles.profiles[target] = replace(
            profiles.profiles[target], phone="+79998887766"
        )
        return preparation

    monkeypatch.setattr(users, "prepare_legacy_max_attachment", changed)
    result = await verifier.verify_code(target, code.code)
    assert result.__class__.__name__ == "VerificationLinkSuccess"
    assert profiles.profiles[target].phone == "+79998887766"


@pytest.mark.asyncio
async def test_direct_legacy_wrapper_only_changes_permitted_attachment_fields():
    users, profiles, codes, target, verifier, _ = await environment()
    roles = verifier.user_role_service
    roles.transaction_manager = verifier.transaction_manager
    before = users.users[target]
    result = await roles.link_max_account(
        "new-max",
        "https://instagram.com/test_user",
        "Requested new username",
        "recorded-chat",
    )
    assert result.state == "ready" and result.reason == "attached"
    assert users.users[target] == replace(
        before, max_id="new-max", max_chat_id="recorded-chat"
    )
    again = await roles.link_max_account(
        "new-max",
        "https://instagram.com/test_user",
        "Another name",
        "another-chat",
    )
    assert again.state == "same_account"
    assert users.users[target] == result.user


@pytest.mark.asyncio
async def test_sql_adapters_do_not_accept_arbitrary_or_missing_transaction():
    from types import SimpleNamespace

    from ugc_bot.infrastructure.db.repositories.instagram import (
        SqlAlchemyInstagramVerificationRepository,
    )
    from ugc_bot.infrastructure.db.repositories.profiles import (
        SqlAlchemyBloggerProfileRepository,
    )
    from ugc_bot.infrastructure.db.repositories.user import (
        SqlAlchemyUserRepository,
    )

    users = SqlAlchemyUserRepository(None)
    profiles = SqlAlchemyBloggerProfileRepository(None)
    codes = SqlAlchemyInstagramVerificationRepository(None)
    for session in (
        None,
        object(),
        SimpleNamespace(in_transaction=lambda: True),
    ):
        assert not users.legacy_confirmation_supported(
            session, (users, profiles, codes)
        )
        plan = await users.prepare_legacy_max_attachment(
            uuid4(), max_id="requested", session=session
        )
        assert not plan.protected
        assert (
            await users.attach_prepared_max(plan, session=session)
        ).state == "unavailable"
        assert (
            await profiles.current_legacy_profile(uuid4(), session=session)
            is None
        )
        assert (
            await codes.current_legacy_code(
                uuid4(), uuid4(), "SYNTHETIC", session=session
            )
            is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [None, "", "bad/native", "   "])
async def test_direct_wrapper_refuses_absent_or_invalid_native_identity(
    native,
):
    users, profiles, codes, target, verifier, _ = await environment()
    roles = verifier.user_role_service
    roles.transaction_manager = verifier.transaction_manager
    original = users.users[target]
    result = await roles.link_max_account(
        native, "https://instagram.com/test_user", "ignored"
    )
    assert result.state == "unavailable"
    assert result.reason == "native_identity_invalid"
    assert users.users[target] == original
