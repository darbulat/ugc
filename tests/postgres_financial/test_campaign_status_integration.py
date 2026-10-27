"""Current campaign navigation and native identity refusals through real SQL."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, func, select, update

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial import test_campaign_runtime as runtime
from tests.postgres_financial.test_campaign_drafts import (
    configure,
    draft_command,
)
from tests.postgres_financial.test_campaign_foundation import (
    command,
    execute,
    policy_payload,
    view,
)
from ugc_bot.infrastructure.db.campaign_models import (
    COMMANDS as FOUNDATION_COMMANDS,
)
from ugc_bot.infrastructure.db.campaign_review_models import (
    COMMANDS as DRAFT_COMMANDS,
)
from ugc_bot.infrastructure.db.models import BloggerProfileModel, UserModel
from ugc_bot.miniapp.api import router
from ugc_bot.miniapp.campaign_moderation_api import (
    create_campaign_moderation_router,
)
from ugc_bot.miniapp.campaign_runtime_api import create_campaign_runtime_router

campaign_env = runtime.campaign_env
financial_pg_engine = runtime.financial_pg_engine


@pytest.mark.asyncio
async def test_navigation_uses_profile_and_retained_publisher_grant(
    campaign_env,
):
    env = campaign_env
    hidden = dict.fromkeys(
        ("workbench", "settings", "consent", "administration"), False
    )
    assert (await view(env, "foreign"))["navigation"] == hidden
    assert (await view(env, "owner"))["navigation"] == hidden
    assert (await view(env, "creator"))["navigation"] == {
        **hidden,
        "settings": True,
        "consent": True,
    }
    assert (await view(env, "admin"))["navigation"] == {
        **hidden,
        "settings": True,
        "workbench": True,
        "administration": True,
    }
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(BloggerProfileModel)
            .where(
                BloggerProfileModel.user_id == env["users"]["creator"].user_id
            )
            .values(confirmed=False)
        )
    assert (await view(env, "creator"))["navigation"]["consent"] is True
    await execute(env, command(env, "publish", **policy_payload()))
    await execute(
        env,
        command(
            env,
            "grant",
            owner_id=str(env["users"]["owner"].user_id),
            reason="Synthetic permission",
        ),
    )
    await execute(
        env,
        command(
            env,
            "revoke",
            expected=1,
            owner_id=str(env["users"]["owner"].user_id),
            reason="Synthetic revocation",
        ),
    )
    retained = await view(env, "owner")
    assert retained["publisher"] == {"active": False, "version": 2}
    assert retained["navigation"] == {
        **hidden,
        "workbench": True,
        "settings": True,
    }


@pytest.mark.asyncio
async def test_prior_consent_keeps_unsubscribe_settings_after_profile_loss(
    campaign_env,
):
    env = campaign_env
    await runtime.approved(env)
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            delete(BloggerProfileModel).where(
                BloggerProfileModel.user_id == env["users"]["creator"].user_id
            )
        )
    result = await view(env, "creator")
    assert result["has_creator_profile"] is False
    assert result["consent"]["active"] is True
    assert result["navigation"] == {
        "workbench": False,
        "settings": True,
        "consent": True,
        "administration": False,
    }
    assert result["can_unsubscribe"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint", ["admin/queue", "recipient/view", "recipient/respond"]
)
async def test_native_remap_returns_campaign_denial_after_database_refresh(
    campaign_env, endpoint
):
    env = campaign_env
    services, _, submitted = await runtime.approved(env)
    role = "admin" if endpoint == "admin/queue" else "creator"
    stale = runtime.proof(env, role)
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == stale.user_id)
            .values(telegram_id="9" + stale.external_id)
        )

    async def resolve(*args, **kwargs):
        return stale

    app = FastAPI()
    app.state.dispatcher = {
        **services,
        "transaction_manager": env["container"].transaction_manager,
    }
    app.include_router(create_campaign_moderation_router(resolve))
    app.include_router(create_campaign_runtime_router(resolve))
    body = {"init_data": "synthetic already resolved signed identity"}
    if endpoint.startswith("recipient/"):
        body["campaign_id"] = str(submitted.campaign_id)
    if endpoint.endswith("respond"):
        body.update(
            operation_key="stale", expected_version=0, choice="interested"
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post("/campaigns/" + endpoint, json=body)
    assert result.status_code == 403, result.text
    assert result.json() == {"detail": "campaign_principal_changed"}
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "endpoint", ["settings", "consent/allow", "owned/draft", "owned/detail"]
)
async def test_production_foundation_and_draft_routes_reject_remap_and_rollback(
    campaign_env, platform, endpoint
):
    env = campaign_env
    await configure(env)
    container = env["container"]
    graph = container.build_bot_services()
    role = "creator" if endpoint in ("settings", "consent/allow") else "owner"
    user = env["users"][role]
    field = "telegram_id" if platform == "telegram" else "max_id"
    if platform == "max":
        async with container.transaction_manager.transaction() as db:
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == user.user_id)
                .values(max_id=user.telegram_id)
            )
    body = {
        "platform": platform,
        "init_data": generate_init_data(
            "test-token", int(user.telegram_id), "synthetic-native-race"
        ),
    }
    key = "native-race-" + endpoint.replace("/", "-")
    if endpoint == "consent/allow":
        body.update(
            operation_key=key,
            expected_version=1,
            policy_version=env["publication"]["version"],
            terms_hash=env["settings"]["policy"]["terms_hash"],
            consent_context=env["settings"]["consent_context"],
        )
    elif endpoint == "owned/draft":
        body.update(
            operation_key=key,
            expected_version=0,
            policy_version=env["publication"]["version"],
            terms_hash=env["settings"]["policy"]["terms_hash"],
            content={"title": "Task", "text": "Brief"},
            segment={},
        )
    elif endpoint == "owned/detail":
        async with container.transaction_manager.transaction() as db:
            draft = await graph["campaign_review_service"].save_draft(
                draft_command(env), session=db
            )
        body["campaign_id"] = draft["campaign_id"]
    roles = graph["user_role_service"]

    async def remap_after_lookup(*args, **kwargs):
        resolved = await roles.get_user(*args, **kwargs)
        assert resolved.user_id == user.user_id
        async with container.transaction_manager.transaction() as db:
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == user.user_id)
                .values(**{field: "9" + user.telegram_id})
            )
        return resolved

    app = FastAPI()
    app.state.config = container._config
    app.state.dispatcher = {
        **graph,
        "user_role_service": SimpleNamespace(get_user=remap_after_lookup),
    }
    app.include_router(router, prefix="/miniapp")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/miniapp/api/campaigns/" + endpoint, json=body
        )
    assert result.status_code == 403, result.text
    assert result.json() == {"detail": "campaign_principal_changed"}
    async with container.transaction_manager.transaction() as db:
        for commands in (FOUNDATION_COMMANDS, DRAFT_COMMANDS):
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(commands)
                    .where(
                        commands.c.actor_id == user.user_id,
                        commands.c.operation_key == key,
                    )
                )
                == 0
            )
