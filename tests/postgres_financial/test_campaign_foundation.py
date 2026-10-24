"""Real persisted policy/consent authority, independent of staff and money."""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, insert, select, update

from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_blogger_profile,
    create_test_user,
)
from tests.postgres_financial.test_order_intake import Clock
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.campaigns import LIMIT_NAMES, CampaignCommand
from ugc_bot.infrastructure.db.campaign_models import POLICIES
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    UserModel,
    UserReferralBindingModel,
)


@pytest_asyncio.fixture
async def campaign_env(financial_pg_engine):
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "MAX_BOT_TOKEN": "test-token",
            "DATABASE_URL": financial_pg_engine.url.render_as_string(
                hide_password=False
            ),
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
        }
    )
    container = Container(config)
    repos = container.build_repos()
    users = {}
    for role in ("admin", "owner", "creator", "foreign"):
        users[role] = await create_test_user(
            repos["user_repo"],
            external_id=str(uuid4().int % 10**12 + 1),
            admin=role == "admin",
            username="safe-" + role,
        )
    await create_test_blogger_profile(
        repos["blogger_repo"],
        users["creator"].user_id,
        instagram_url="https://instagram.com/synthetic_" + uuid4().hex,
    )
    await create_test_advertiser_profile(
        repos["advertiser_repo"], users["owner"].user_id, brand="safe-owner"
    )
    async with container.transaction_manager.transaction() as db:
        baseline = await db.scalar(select(func.max(POLICIES.c.version))) or 0
        await db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == users["creator"].user_id)
            .values(
                confirmed=True, instagram_user_id="canonical-" + uuid4().hex
            )
        )
        await db.execute(
            insert(UserReferralBindingModel).values(
                referrer_user_id=users["owner"].user_id,
                referred_user_id=users["creator"].user_id,
            )
        )
    try:
        yield {
            "container": container,
            "users": users,
            "clock": Clock(),
            "base_policy_version": baseline,
            "pg": financial_pg_engine,
        }
    finally:
        await container.session_factory.kw["bind"].dispose()


def command(env, action, *, role="admin", expected=None, **payload):
    if expected is None:
        expected = env["base_policy_version"] if action == "publish" else 0
    return CampaignCommand(
        env["users"][role].user_id,
        "synthetic-" + uuid4().hex,
        action,
        expected,
        payload,
    )


def policy_payload():
    return {
        "terms_version": "synthetic-terms-" + uuid4().hex,
        "default_locale": "ru",
        "terms": {
            "ru": "Синтетические условия для теста. Можно отписаться.",
            "en": "Synthetic test terms. Unsubscribe at any time.",
        },
        "limits": dict.fromkeys(LIMIT_NAMES, 7),
        "reason": "Synthetic configuration, not a product quota",
    }


async def execute(env, cmd):
    service = env["container"].build_bot_services()["campaign_service"]
    async with env["container"].transaction_manager.transaction() as session:
        return await service.execute(cmd, session=session)


async def view(env, role="creator"):
    service = env["container"].build_bot_services()["campaign_service"]
    async with env["container"].transaction_manager.transaction() as session:
        return await service.view(env["users"][role].user_id, session=session)


async def ready(env):
    published = await execute(env, command(env, "publish", **policy_payload()))
    await execute(
        env,
        command(
            env,
            "grant",
            owner_id=str(env["users"]["owner"].user_id),
            reason="Synthetic publisher approval",
        ),
    )
    return published


@pytest.mark.asyncio
async def test_real_publication_grant_opt_in_and_paused_unsubscribe(
    campaign_env,
):
    env = campaign_env
    before = await view(env)
    assert before["consent"]["effective"] is False
    publication = await ready(env)
    settings = await view(env)
    assert (
        settings["inviter"]["label"] == "safe-owner" and settings["can_consent"]
    )
    assert "telegram_id" not in str(settings) and "phone" not in str(settings)
    cmd = command(
        env,
        "consent",
        role="creator",
        policy_version=publication["version"],
        terms_hash=settings["policy"]["terms_hash"],
        consent_context=settings["consent_context"],
    )
    result = await execute(env, cmd)
    assert result["version"] == 1 and result["is_current"]
    assert (await execute(env, cmd))["receipt_id"] == result["receipt_id"]
    assert (await view(env))["consent"]["effective"] is True
    await execute(
        env,
        command(
            env,
            "suspend",
            expected=publication["version"],
            reason="Pause sending",
        ),
    )
    assert not (await view(env))["can_consent"]
    await execute(env, command(env, "unsubscribe", role="creator", expected=1))
    settings = await view(env)
    assert (
        not settings["consent"]["effective"]
        and settings["consent"]["version"] == 2
    )


@pytest.mark.asyncio
async def test_staff_boolean_and_registration_agreement_never_authorize(
    campaign_env,
):
    env = campaign_env
    with pytest.raises(PermissionError):
        await execute(
            env, command(env, "publish", role="owner", **policy_payload())
        )
    await ready(env)
    settings = await view(env)
    assert not settings["consent"]["effective"]
    with pytest.raises(ValueError, match="unexpected"):
        await execute(
            env,
            command(
                env,
                "consent",
                role="creator",
                policy_version=1,
                terms_hash=settings["policy"]["terms_hash"],
                consent_context=settings["consent_context"],
                owner_id=str(env["users"]["foreign"].user_id),
            ),
        )
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["users"]["admin"].user_id)
            .values(admin=False)
        )
    with pytest.raises(PermissionError):
        await execute(
            env,
            command(
                env,
                "revoke",
                owner_id=str(env["users"]["owner"].user_id),
                expected=1,
                reason="No current authority",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "loss",
    [
        "identity",
        "binding",
        "owner",
        "creator",
        "contact",
        "publisher",
        "terms",
    ],
)
async def test_current_source_loss_blocks_opt_in_but_not_own_unsubscribe(
    campaign_env, loss
):
    from sqlalchemy import delete

    from ugc_bot.domain.campaigns import CampaignConflict

    env = campaign_env
    published = await ready(env)
    settings = await view(env)
    original = command(
        env,
        "consent",
        role="creator",
        policy_version=published["version"],
        terms_hash=settings["policy"]["terms_hash"],
        consent_context=settings["consent_context"],
    )
    await execute(env, original)
    if loss == "publisher":
        await execute(
            env,
            command(
                env,
                "revoke",
                expected=1,
                owner_id=str(env["users"]["owner"].user_id),
                reason="Current publisher revoked",
            ),
        )
    elif loss == "terms":
        await execute(
            env,
            command(
                env,
                "publish",
                expected=published["version"],
                **policy_payload(),
            ),
        )
    else:
        async with env["container"].transaction_manager.transaction() as db:
            if loss == "identity":
                stmt = (
                    update(BloggerProfileModel)
                    .where(
                        BloggerProfileModel.user_id
                        == env["users"]["creator"].user_id
                    )
                    .values(confirmed=False)
                )
            elif loss == "binding":
                stmt = delete(UserReferralBindingModel).where(
                    UserReferralBindingModel.referred_user_id
                    == env["users"]["creator"].user_id
                )
            else:
                target = "owner" if loss == "owner" else "creator"
                values = (
                    {"telegram_id": None}
                    if loss == "contact"
                    else {"status": "pause"}
                )
                stmt = (
                    update(UserModel)
                    .where(UserModel.user_id == env["users"][target].user_id)
                    .values(**values)
                )
            await db.execute(stmt)
    current = await view(env)
    assert not current["consent"]["effective"] and current["can_unsubscribe"]
    with pytest.raises((PermissionError, CampaignConflict)):
        await execute(env, original)
    await execute(env, command(env, "unsubscribe", role="creator", expected=1))
    assert not (await view(env))["consent"]["active"]


@pytest.mark.asyncio
async def test_immutable_receipt_conflict_stale_review_and_terms_version(
    campaign_env,
):
    from dataclasses import replace

    from ugc_bot.domain.campaigns import CampaignConflict

    env = campaign_env
    publish = command(env, "publish", **policy_payload())
    result = await execute(env, publish)
    changed = replace(
        publish, payload={**publish.payload, "reason": "Changed intent"}
    )
    with pytest.raises(CampaignConflict, match="operation_conflict"):
        await execute(env, changed)
    with pytest.raises(CampaignConflict, match="version_conflict"):
        await execute(
            env,
            command(
                env,
                "suspend",
                expected=result["version"] - 1,
                reason="Stale current version",
            ),
        )
    await execute(
        env, command(env, "suspend", expected=result["version"], reason="Pause")
    )
    replay = await execute(env, publish)
    assert (
        replay["receipt_id"] == result["receipt_id"]
        and not replay["is_current"]
    )
    with pytest.raises(CampaignConflict, match="terms_version_reused"):
        await execute(
            env,
            command(
                env,
                "publish",
                expected=result["version"] + 1,
                **{**publish.payload, "terms": {"ru": "Different full terms"}},
            ),
        )
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["users"]["admin"].user_id)
            .values(status="pause")
        )
    with pytest.raises(PermissionError):
        await execute(env, publish)


@pytest.mark.asyncio
async def test_read_snapshot_and_admin_accounts_are_scoped(
    campaign_env,
):
    from sqlalchemy import text

    from ugc_bot.infrastructure.db.repositories.campaigns import (
        SqlAlchemyCampaignRepository,
    )

    env = campaign_env
    repo = SqlAlchemyCampaignRepository()
    async with env["container"].transaction_manager.transaction() as db:
        await repo.begin_snapshot(session=db)
        assert await db.scalar(text("SHOW transaction_read_only")) == "on"
        assert (
            await db.scalar(text("SHOW transaction_isolation"))
            == "repeatable read"
        )
    service = env["container"].build_bot_services()["campaign_service"]
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(PermissionError):
            await service.accounts(
                env["users"]["creator"].user_id, "", 0, session=db
            )
    async with env["container"].transaction_manager.transaction() as db:
        records = await service.accounts(
            env["users"]["admin"].user_id,
            str(env["users"]["owner"].user_id),
            0,
            session=db,
        )
        assert len(records["accounts"]) == 1
        assert set(records["accounts"][0]) == {
            "owner_id",
            "label",
            "version",
            "active",
            "status",
            "can_grant",
            "can_revoke",
        }
        assert records["accounts"][0]["label"] == "safe-owner"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table",
    [
        "campaign_foundation_commands",
        "campaign_policy_events",
        "campaign_publisher_events",
        "campaign_consent_events",
    ],
)
@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE {table} SET recorded_at=recorded_at",
        "DELETE FROM {table}",
        "TRUNCATE {table} CASCADE",
    ],
)
async def test_campaign_facts_cannot_be_rewritten_or_removed(
    campaign_env, table, mutation
):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    env = campaign_env
    await ready(env)
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(IntegrityError, match="campaign_fact_immutable"):
            await db.execute(text(mutation.format(table=table)))
        await db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_actual_signed_api_persistence_privacy_and_strict_intent(
    campaign_env, platform
):
    import httpx
    from fastapi import FastAPI

    from tests.e2e.miniapp_helpers import generate_init_data
    from ugc_bot.miniapp.api import router

    env = campaign_env
    container = env["container"]
    if platform == "max":
        async with container.transaction_manager.transaction() as db:
            for user in env["users"].values():
                await db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == user.user_id)
                    .values(max_id=user.telegram_id)
                )

    def body(role):
        return {
            "init_data": generate_init_data(
                "test-token", int(env["users"][role].telegram_id), "synthetic"
            ),
            "platform": platform,
        }

    def app(value):
        result = FastAPI()
        result.include_router(router, prefix="/miniapp")
        result.state.config = value._config
        result.state.dispatcher = value.build_bot_services()
        return result

    prefix = "/miniapp/api/campaigns"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(container)),
        base_url="http://test",
    ) as client:
        published = await client.post(
            prefix + "/policy/publish",
            json={
                **body("admin"),
                "operation_key": "api-" + uuid4().hex,
                "expected_version": env["base_policy_version"],
                **policy_payload(),
            },
        )
        assert published.status_code == 200, published.text
        version = published.json()["version"]
        grant = await client.post(
            prefix + "/publishers/grant",
            json={
                **body("admin"),
                "operation_key": "api-" + uuid4().hex,
                "expected_version": 0,
                "owner_id": str(env["users"]["owner"].user_id),
                "reason": "Actual admin grant",
            },
        )
        assert grant.status_code == 200, grant.text
        settings = (
            await client.post(prefix + "/settings", json=body("creator"))
        ).json()
        payload = {
            **body("creator"),
            "operation_key": "api-" + uuid4().hex,
            "expected_version": 0,
            "policy_version": version,
            "terms_hash": settings["policy"]["terms_hash"],
            "consent_context": settings["consent_context"],
        }
        for extra in (
            {"owner_id": str(env["users"]["foreign"].user_id)},
            {"consent": True},
            {"verified": True},
            {"is_admin": True},
        ):
            assert (
                await client.post(
                    prefix + "/consent/allow", json={**payload, **extra}
                )
            ).status_code == 422
        assert (
            await client.post(
                prefix + "/settings?owner_id=foreign", json=body("creator")
            )
        ).status_code == 422
        assert (
            await client.post(prefix + "/admin/accounts", json=body("owner"))
        ).status_code == 403
        missing_context = {
            k: v for k, v in payload.items() if k != "consent_context"
        }
        assert (
            await client.post(prefix + "/consent/allow", json=missing_context)
        ).status_code == 422
        assert (
            await client.post(
                prefix + "/consent/allow",
                json={**payload, "consent_context": "0" * 64},
            )
        ).status_code == 409
        allowed = await client.post(prefix + "/consent/allow", json=payload)
        assert allowed.status_code == 200, allowed.text
        assert (
            await client.post(prefix + "/consent/allow", json=payload)
        ).json()["receipt_id"] == allowed.json()["receipt_id"]
        invalid = {
            **body("admin"),
            "operation_key": "invalid-" + uuid4().hex,
            "expected_version": version,
            **policy_payload(),
        }
        invalid["limits"]["recipients_per_campaign"] = True
        assert (
            await client.post(prefix + "/policy/publish", json=invalid)
        ).status_code == 422
    fresh = Container(container._config)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app(fresh)),
            base_url="http://test",
        ) as client:
            persisted = await client.post(
                prefix + "/settings", json=body("creator")
            )
            assert persisted.json()["consent"]["effective"] is True
            assert (
                "owner_id" not in persisted.text
                and "telegram_id" not in persisted.text
            )
            foreign = await client.post(
                prefix + "/settings", json=body("foreign")
            )
            assert (
                not foreign.json()["consent"]["active"]
                and foreign.json()["inviter"] is None
            )
            revoked_publisher = await client.post(
                prefix + "/publishers/revoke",
                json={
                    **body("admin"),
                    "operation_key": "revoke-" + uuid4().hex,
                    "expected_version": 1,
                    "owner_id": str(env["users"]["owner"].user_id),
                    "reason": "Current admin revocation",
                },
            )
            assert revoked_publisher.status_code == 200, revoked_publisher.text
            revoked = await client.post(
                prefix + "/consent/revoke",
                json={
                    **body("creator"),
                    "operation_key": "unsubscribe-" + uuid4().hex,
                    "expected_version": 1,
                },
            )
            assert revoked.status_code == 200
    finally:
        await fresh.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("writer_kind", ["admin", "profile", "binding"])
async def test_actual_authority_and_identity_writers_wait_for_committed_command(
    campaign_env, writer_kind
):
    import asyncio

    from sqlalchemy import delete, text

    from ugc_bot.application.services.campaign_service import (
        CampaignFoundationService,
    )
    from ugc_bot.infrastructure.db.repositories.campaigns import (
        SqlAlchemyCampaignRepository,
    )
    from ugc_bot.infrastructure.db.session import create_session_factory

    env = campaign_env
    if writer_kind == "admin":
        cmd = command(env, "publish", **policy_payload())
        stmt = (
            update(UserModel)
            .where(UserModel.user_id == env["users"]["admin"].user_id)
            .values(admin=False)
        )
    else:
        published = await ready(env)
        settings = await view(env)
        cmd = command(
            env,
            "consent",
            role="creator",
            policy_version=published["version"],
            terms_hash=settings["policy"]["terms_hash"],
            consent_context=settings["consent_context"],
        )
        stmt = (
            update(BloggerProfileModel)
            .where(
                BloggerProfileModel.user_id == env["users"]["creator"].user_id
            )
            .values(confirmed=False)
            if writer_kind == "profile"
            else delete(UserReferralBindingModel).where(
                UserReferralBindingModel.referred_user_id
                == env["users"]["creator"].user_id
            )
        )
    sessions = create_session_factory(
        env["container"]._config.db.database_url, pool_size=3
    )
    service = CampaignFoundationService(
        SqlAlchemyCampaignRepository(), env["clock"]
    )
    started = asyncio.Future()

    async def writer():
        async with sessions.begin() as db:
            started.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
            await db.execute(stmt)

    task = None
    try:
        async with sessions.begin() as holding:
            await service.execute(cmd, session=holding)
            task = asyncio.create_task(writer())
            pid = await started
            async with sessions() as monitor:
                async with asyncio.timeout(3):
                    while not await monitor.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid))>0"),
                        {"pid": pid},
                    ):
                        assert not task.done()
                        await asyncio.sleep(0.01)
            assert not task.done()
        await asyncio.wait_for(task, 3)
        current = await view(
            env, "admin" if writer_kind == "admin" else "creator"
        )
        assert (
            not current["can_admin"]
            if writer_kind == "admin"
            else not current["consent"]["effective"]
        )
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await sessions.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_competing_opt_ins_have_one_committed_version(campaign_env):
    import asyncio

    from ugc_bot.application.services.campaign_service import (
        CampaignFoundationService,
    )
    from ugc_bot.domain.campaigns import CampaignConflict
    from ugc_bot.infrastructure.db.repositories.campaigns import (
        SqlAlchemyCampaignRepository,
    )
    from ugc_bot.infrastructure.db.session import create_session_factory

    env = campaign_env
    published = await ready(env)
    settings = await view(env)
    sessions = create_session_factory(
        env["container"]._config.db.database_url, pool_size=2
    )
    service = CampaignFoundationService(
        SqlAlchemyCampaignRepository(), env["clock"]
    )

    async def choose():
        async with sessions.begin() as db:
            return await service.execute(
                command(
                    env,
                    "consent",
                    role="creator",
                    policy_version=published["version"],
                    terms_hash=settings["policy"]["terms_hash"],
                    consent_context=settings["consent_context"],
                ),
                session=db,
            )

    try:
        outcomes = await asyncio.gather(
            choose(), choose(), return_exceptions=True
        )
        assert sum(isinstance(v, dict) for v in outcomes) == 1
        assert sum(isinstance(v, CampaignConflict) for v in outcomes) == 1
        assert (await view(env))["consent"]["version"] == 1
    finally:
        await sessions.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_no_role_or_nonexistent_target_cannot_create_configuration(
    campaign_env,
):
    env = campaign_env
    service = env["container"].build_bot_services()["campaign_service"]
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(ValueError, match="typed_campaign"):
            await service.execute(object(), session=db)
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(ValueError, match="invalid_page"):
            await service.accounts(
                env["users"]["admin"].user_id, "", -1, session=db
            )
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(LookupError):
            await service.view(uuid4(), session=db)
    await ready(env)
    for action, payload, error in (
        (
            "grant",
            {"owner_id": str(uuid4()), "reason": "Missing target"},
            LookupError,
        ),
        (
            "revoke",
            {
                "owner_id": str(env["users"]["foreign"].user_id),
                "reason": "No prior permission",
            },
            ValueError,
        ),
        ("unsubscribe", {}, ValueError),
    ):
        with pytest.raises(error):
            await execute(
                env,
                command(
                    env,
                    action,
                    role="creator" if action == "unsubscribe" else "admin",
                    **payload,
                ),
            )
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["users"]["foreign"].user_id)
            .values(status="pause")
        )
    with pytest.raises(ValueError, match="active_owner"):
        await execute(
            env,
            command(
                env,
                "grant",
                owner_id=str(env["users"]["foreign"].user_id),
                reason="Inactive target",
            ),
        )
    async with env["container"].transaction_manager.transaction() as db:
        result = await service.accounts(
            env["users"]["admin"].user_id,
            "private-contact-search",
            0,
            session=db,
        )
        assert result["accounts"] == []


@pytest.mark.asyncio
async def test_binding_changed_while_waiting_on_history_requires_refresh(
    campaign_env,
):
    import asyncio

    from sqlalchemy import delete, text

    from ugc_bot.application.services.campaign_service import (
        CampaignFoundationService,
    )
    from ugc_bot.domain.campaigns import CampaignConflict
    from ugc_bot.infrastructure.db.repositories.campaigns import (
        SqlAlchemyCampaignRepository,
    )
    from ugc_bot.infrastructure.db.session import create_session_factory

    env = campaign_env
    published = await ready(env)
    settings = await view(env)
    sessions = create_session_factory(
        env["container"]._config.db.database_url, pool_size=3
    )
    service = CampaignFoundationService(
        SqlAlchemyCampaignRepository(), env["clock"]
    )
    cmd = command(
        env,
        "consent",
        role="creator",
        policy_version=published["version"],
        terms_hash=settings["policy"]["terms_hash"],
        consent_context=settings["consent_context"],
    )
    started = asyncio.Future()
    task = None

    async def choose():
        async with sessions.begin() as db:
            started.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
            return await service.execute(cmd, session=db)

    try:
        async with sessions.begin() as holding:
            await holding.execute(
                delete(UserReferralBindingModel).where(
                    UserReferralBindingModel.referred_user_id
                    == env["users"]["creator"].user_id
                )
            )
            task = asyncio.create_task(choose())
            pid = await started
            async with sessions() as monitor:
                async with asyncio.timeout(3):
                    while not await monitor.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid))>0"),
                        {"pid": pid},
                    ):
                        assert not task.done()
                        await asyncio.sleep(0.01)
        with pytest.raises(CampaignConflict, match="inviter_changed"):
            await task
        assert (await view(env))["consent"]["version"] == 0
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await sessions.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_no_private_username_is_substituted_for_missing_public_label(
    campaign_env,
):
    from sqlalchemy import delete

    from ugc_bot.infrastructure.db.models import AdvertiserProfileModel

    env = campaign_env
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            delete(AdvertiserProfileModel).where(
                AdvertiserProfileModel.user_id == env["users"]["owner"].user_id
            )
        )
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["users"]["owner"].user_id)
            .values(
                username="PRIVATE_IDENTITY_MUST_NOT_LEAK",
                telegram="PRIVATE_CONTACT_MUST_NOT_LEAK",
            )
        )
    current = await view(env)
    assert current["inviter"]["label"] is None
    assert "PRIVATE_" not in str(current)
