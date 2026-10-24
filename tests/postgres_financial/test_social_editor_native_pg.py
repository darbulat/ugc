"""Signed main-router social authority and coherent actual PostgreSQL facts."""

import asyncio
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4, uuid5

import pytest
import pytest_asyncio
from sqlalchemy import delete, event, select, update

from tests.helpers.social_editor_pg import (
    ActorGate,
    EditorTrace,
    SocialEditorCase,
    assert_error,
    driver_pid,
    finish,
    observation,
    observe_wait,
)
from ugc_bot.application.services.social_account_service import (
    SocialAccountService,
)
from ugc_bot.application.social_ports import SocialEditorSaved
from ugc_bot.domain.enums import WorkFormat
from ugc_bot.domain.social import SocialAccount, SocialPlatform
from ugc_bot.infrastructure.db.models import BloggerProfileModel, UserModel
from ugc_bot.infrastructure.db.social_models import SocialAccountModel
from ugc_bot.miniapp import social_api


@pytest.fixture(scope="session")
def social_pg_evidence():
    records = []
    yield records
    destination = os.environ.get("SOCIAL_EDITOR_PG_EVIDENCE_PATH")
    if destination:
        Path(destination).write_text(json.dumps(records, indent=2) + "\n")


@pytest_asyncio.fixture
async def social_case(financial_pg_engine):
    case = SocialEditorCase(financial_pg_engine)
    try:
        await case.seed()
        yield case
    finally:
        await case.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("action", ["list", "save", "remove"])
@pytest.mark.parametrize("change", ["clear", "remap"])
async def test_mapping_first_denies_before_private_source(
    social_case, platform, action, change, social_pg_evidence
):
    case, gate, task = social_case, ActorGate("before"), None
    await case.seed_account()
    try:
        with EditorTrace(case, gate) as trace:
            task = asyncio.create_task(case.post(action, platform))
            reader = await asyncio.wait_for(gate.reached, 3)
            writer = await asyncio.wait_for(case.mutate(change, platform), 3)
            after_writer = await case.effects()
            gate.release.set()
            response = await asyncio.wait_for(task, 4)
        assert_error(response, 403, "financial_principal_changed")
        trace.assert_actor_only()
        if action == "list":
            trace.assert_read_only()
        assert reader["pid"] != writer
        assert await case.effects() == after_writer
        social_pg_evidence.append(
            observation(
                trace,
                platform=platform,
                ordering="mapping_first:" + action + ":" + change,
                writer=writer,
            )
        )
    finally:
        gate.release.set()
        await finish(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("action", ["list", "save", "remove"])
@pytest.mark.parametrize("status", ["blocked", "bot_blocked", "deleted"])
async def test_status_first_denies_before_private_source(
    social_case, platform, action, status, social_pg_evidence
):
    case, gate, task = social_case, ActorGate("before"), None
    await case.seed_account()
    try:
        with EditorTrace(case, gate) as trace:
            task = asyncio.create_task(case.post(action, platform))
            await asyncio.wait_for(gate.reached, 3)
            writer = await asyncio.wait_for(case.mutate(status, platform), 3)
            after_writer = await case.effects()
            gate.release.set()
            response = await asyncio.wait_for(task, 4)
        assert_error(response, 403, "social_account_unavailable")
        trace.assert_actor_only()
        if action == "list":
            trace.assert_read_only()
        assert await case.effects() == after_writer
        social_pg_evidence.append(
            observation(
                trace,
                platform=platform,
                ordering="status_first:" + action + ":" + status,
                writer=writer,
            )
        )
    finally:
        gate.release.set()
        await finish(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_profile_first_current_confirmation_denies_save(
    social_case, platform
):
    case, gate, task = social_case, ActorGate("before"), None
    try:
        with EditorTrace(case, gate) as trace:
            task = asyncio.create_task(case.post("save", platform))
            await asyncio.wait_for(gate.reached, 3)
            await asyncio.wait_for(case.mutate("profile", platform), 3)
            gate.release.set()
            response = await asyncio.wait_for(task, 4)
        assert_error(response, 400, "social_instagram_verification_required")
        trace.assert_user_first_write()
        assert (await case.effects())["accounts"] == []
    finally:
        gate.release.set()
        await finish(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("action", ["save", "remove"])
@pytest.mark.parametrize("change", ["clear", "blocked", "profile"])
async def test_editor_user_fence_blocks_native_status_and_profile_writers(
    social_case, platform, action, change, social_pg_evidence
):
    case, gate, task, writer_task = social_case, ActorGate("after"), None, None
    if action == "remove":
        await case.seed_account()
    try:
        with EditorTrace(case, gate) as trace:
            task = asyncio.create_task(case.post(action, platform))
            actor = await asyncio.wait_for(gate.reached, 3)
            ready = asyncio.Future()
            writer_task = asyncio.create_task(
                case.mutate(change, platform, ready=ready)
            )
            writer = await asyncio.wait_for(ready, 3)
            wait = await observe_wait(case, writer, actor["pid"])
            assert not writer_task.done()
            gate.release.set()
            response = await asyncio.wait_for(task, 4)
            assert await asyncio.wait_for(writer_task, 4) == writer
        assert response.status_code == 200, response.text
        trace.assert_user_first_write()
        assert trace.only()["ended"] == "commit"
        effects = await case.effects()
        assert bool(effects["accounts"]) == (action == "save")
        if change == "clear":
            assert effects["user"][platform == "max"] is None
        if change == "blocked":
            assert effects["user"][3] == "blocked"
        social_pg_evidence.append(
            observation(
                trace,
                platform=platform,
                ordering="editor_first:" + action + ":" + change,
                writer=writer,
                wait=wait,
            )
        )
    finally:
        gate.release.set()
        await finish(task)
        await finish(writer_task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_user_fence_blocks_http_insert_for_previously_absent_platform(
    social_case, platform, social_pg_evidence
):
    case, task = social_case, None
    try:
        async with case.factory() as blocker:
            await blocker.begin()
            blocker_pid = await driver_pid(blocker)
            await blocker.execute(
                select(UserModel.user_id)
                .where(UserModel.user_id == case.user.user_id)
                .with_for_update(key_share=True)
            )
            assert not list(
                await blocker.scalars(
                    select(SocialAccountModel).where(
                        SocialAccountModel.user_id == case.user.user_id,
                        SocialAccountModel.platform == "youtube",
                    )
                )
            )
            gate = ActorGate("before")
            gate.release.set()
            with EditorTrace(case, gate) as trace:
                task = asyncio.create_task(case.post("save", platform))
                actor = await asyncio.wait_for(gate.reached, 3)
                wait = await observe_wait(case, actor["pid"], blocker_pid)
                assert not task.done()
                await blocker.commit()
                response = await asyncio.wait_for(task, 4)
            assert response.status_code == 200, response.text
            trace.assert_user_first_write()
            assert len((await case.effects())["accounts"]) == 1
            social_pg_evidence.append(
                observation(
                    trace,
                    platform=platform,
                    ordering="absent_platform_user_fence_dependency",
                    writer=blocker_pid,
                    wait=wait,
                )
            )
    finally:
        await finish(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("change", ["native", "status", "private"])
async def test_snapshot_first_is_coherent_while_writer_commits_without_wait(
    social_case, platform, change, social_pg_evidence
):
    case, gate, task = social_case, ActorGate("after"), None
    old = await case.seed_account("tiktok")
    try:
        with EditorTrace(case, gate) as trace:
            task = asyncio.create_task(case.post("list", platform))
            await asyncio.wait_for(gate.reached, 3)
            writer = await asyncio.wait_for(
                case.coherent_change(change, platform), 3
            )
            after_writer = await case.effects()
            gate.release.set()
            response = await asyncio.wait_for(task, 4)
        assert response.status_code == 200, response.text
        trace.assert_read_only()
        data = response.json()
        assert data["next_platform"] == "youtube"
        assert [a["platform"] for a in data["accounts"]] == [
            "instagram",
            "tiktok",
        ]
        assert data["accounts"][0]["verified"] is True
        assert data["accounts"][0]["work_format"] == "ugc_only"
        assert data["accounts"][0]["url"].endswith("_old")
        assert data["accounts"][1] == old
        assert await case.effects() == after_writer
        fresh = await case.post("list", platform)
        if change == "native":
            assert_error(fresh, 404, "existing_financial_account_required")
        elif change == "status":
            assert_error(fresh, 403, "social_account_unavailable")
        else:
            assert fresh.status_code == 200, fresh.text
            new = fresh.json()
            assert new["next_platform"] == "instagram"
            assert [a["platform"] for a in new["accounts"]] == [
                "instagram",
                "youtube",
            ]
            assert new["accounts"][0]["verified"] is False
            assert new["accounts"][0]["work_format"] == "ads_in_account"
            assert new["accounts"][0]["url"].endswith("_new")
            assert new["accounts"][1]["handle"] == "synthetic_new"
            assert new["accounts"][1]["verified"] is False
        social_pg_evidence.append(
            observation(
                trace,
                platform=platform,
                ordering="snapshot_first:" + change,
                writer=writer,
            )
        )
    finally:
        gate.release.set()
        await finish(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_same_session_cache_preload_in_completed_transaction_is_refreshed(
    social_case, platform
):
    case = social_case
    await case.seed_account()
    factory = case.container.session_factory
    async with factory() as db:
        async with db.begin():
            stale_profile = await db.get(BloggerProfileModel, case.user.user_id)
            stale_account = await db.get(SocialAccountModel, case.account_id)
        assert not db.in_transaction()
        async with case.factory.begin() as writer:
            await writer.execute(
                select(UserModel.user_id)
                .where(UserModel.user_id == case.user.user_id)
                .with_for_update(key_share=True)
            )
            await writer.execute(
                update(BloggerProfileModel)
                .where(BloggerProfileModel.user_id == case.user.user_id)
                .values(confirmed=False, work_format="ads_in_account")
            )
            await writer.execute(
                update(SocialAccountModel)
                .where(SocialAccountModel.account_id == case.account_id)
                .values(url="https://youtube.com/@fresh", handle="fresh")
            )
        assert stale_profile.confirmed is True
        assert stale_account.handle == "synthetic_old"
        with EditorTrace(case) as trace:
            async with db.begin():
                facts = await case.service.editor_repository.read_editor(
                    case.user.user_id,
                    principal=case.principal(platform),
                    session=db,
                )
        trace.assert_read_only()
        assert facts.profile.confirmed is False
        assert facts.profile.work_format == WorkFormat.ADS_IN_ACCOUNT
        assert facts.accounts[0].handle == "fresh"
        assert stale_profile.confirmed is False
        assert stale_account.handle == "fresh"
        # A second fresh root transaction also refuses changed native identity.
        await case.mutate("clear", platform)
        with pytest.raises(ValueError, match="^financial_principal_changed$"):
            async with db.begin():
                await case.service.editor_repository.read_editor(
                    case.user.user_id,
                    principal=case.principal(platform),
                    session=db,
                )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["projection", "detached_result"])
async def test_post_save_failure_before_facade_commit_rolls_back_actual_sql(
    social_case, monkeypatch, failure
):
    case = social_case
    original = SocialAccountService._project
    calls = 0

    def fail_projection(facts, owner):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("private synthetic projection failure")
        return original(facts, owner)

    def fail_result(self):
        raise RuntimeError("private synthetic detached result failure")

    with monkeypatch.context() as patch:
        if failure == "projection":
            patch.setattr(
                SocialAccountService, "_project", staticmethod(fail_projection)
            )
        else:
            patch.setattr(SocialEditorSaved, "__post_init__", fail_result)
        with EditorTrace(case) as trace:
            response = await case.post("save", "telegram")
    assert_error(response, 503, "social_unavailable")
    assert trace.only()["ended"] == "rollback"
    assert any(
        sql.startswith("INSERT INTO CREATOR_SOCIAL_ACCOUNTS")
        for sql in trace.only()["sql"]
    )
    assert (await case.effects())["accounts"] == []
    current = await case.post("save", "telegram")
    assert current.status_code == 200, current.text
    assert len((await case.effects())["accounts"]) == 1


@pytest.mark.asyncio
async def test_later_http_encoding_error_keeps_already_committed_sql(
    social_case, monkeypatch
):
    case = social_case

    def fail_model(*args, **kwargs):
        raise RuntimeError("private synthetic encoding failure")

    with monkeypatch.context() as patch:
        patch.setattr(social_api, "AccountSavedResponse", fail_model)
        with EditorTrace(case) as trace:
            response = await case.post("save", "max")
    assert_error(response, 503, "social_unavailable")
    assert trace.only()["ended"] == "commit"
    assert len((await case.effects())["accounts"]) == 1
    current = await case.post("list", "max")
    assert current.status_code == 200
    assert [a["platform"] for a in current.json()["accounts"]] == [
        "instagram",
        "youtube",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_legacy_idless_prompt_upsert_country_and_rebuild(
    social_case, platform
):
    case = social_case
    assert case.profile.confirmed and case.profile.instagram_user_id is None
    with EditorTrace(case) as trace:
        listed = await case.post("list", platform)
    trace.assert_read_only()
    assert listed.json()["next_platform"] == "tiktok"
    first = await case.post(
        "save",
        platform,
        extra=dict(
            network="tiktok",
            url="https://tiktok.com/@FIRST",
            work_format="ads_in_account",
        ),
    )
    assert first.status_code == 200, first.text
    a = first.json()["account"]
    assert a["handle"] == "first" and a["verified"] is False
    for field in (
        "followers_count",
        "metrics_source",
        "metrics_fetched_at",
        "verified_at",
        "verification_source",
        "external_id",
    ):
        assert a[field] is None
    assert first.json()["next_platform"] == "youtube"
    second = await case.post(
        "save",
        platform,
        extra=dict(network="tiktok", url="https://tiktok.com/@SECOND"),
    )
    assert second.status_code == 200
    b = second.json()["account"]
    assert b["account_id"] == a["account_id"]
    assert b["created_at"] == a["created_at"]
    assert b["handle"] == "second" and b["work_format"] == "ads_in_account"
    next_response = await case.post(
        "list",
        platform,
        extra=dict(skipped=["youtube", "telegram"], include_vk=True),
    )
    assert next_response.json()["next_platform"] == "vk"
    config = case.container._config
    from ugc_bot.container import Container

    rebuilt = Container(config)
    try:
        case.app.state.dispatcher = rebuilt.build_bot_services()
        persisted = await case.post("list", platform)
        assert persisted.status_code == 200
        assert persisted.json()["accounts"][1] == b
    finally:
        case.app.state.dispatcher = case.services
        await rebuilt.dispose()
    assert (await case.effects())["user"][2] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("action", ["list", "save", "remove"])
async def test_signed_unknown_identity_never_registers_or_fills_country(
    social_case, platform, action
):
    case = social_case
    before = await case.effects()
    with EditorTrace(case) as trace:
        response = await case.post(
            action, platform, external=str(uuid4().int % 10**13 + 1)
        )
    assert_error(response, 404, "existing_financial_account_required")
    assert trace.transactions == []
    assert await case.effects() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["new", "pause"])
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("action", ["list", "save", "remove"])
async def test_admitted_current_status_preserves_legacy_editor_behavior(
    social_case, platform, status, action
):
    case = social_case
    if action == "remove":
        await case.seed_account()
    await case.mutate(status, platform)
    with EditorTrace(case) as trace:
        response = await case.post(action, platform)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert (await case.effects())["user"][2:] == (None, status)
    if action == "list":
        trace.assert_read_only()
    else:
        trace.assert_user_first_write()


@pytest.mark.asyncio
@pytest.mark.parametrize("profile_state", ["missing", "unconfirmed"])
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_missing_or_unconfirmed_profile_reads_and_own_cleanup_remain(
    social_case, profile_state, platform
):
    case = social_case
    await case.seed_account()
    if profile_state == "missing":
        # Private SQL fixture mutation; no product profile deletion claim.
        async with case.factory.begin() as db:
            await db.execute(
                delete(BloggerProfileModel).where(
                    BloggerProfileModel.user_id == case.user.user_id
                )
            )
    else:
        await case.mutate("profile", platform)
    listed = await case.post("list", platform)
    assert listed.status_code == 200
    assert listed.json()["next_platform"] == "instagram"
    if profile_state == "missing":
        assert listed.json()["accounts"] == []
    else:
        assert listed.json()["accounts"][0]["verified"] is False
    denied = await case.post("save", platform)
    assert_error(
        denied,
        400,
        "social_creator_profile_required"
        if profile_state == "missing"
        else "social_instagram_verification_required",
    )
    removed = await case.post("remove", platform)
    assert removed.status_code == 200 and removed.json() == dict(removed=True)
    assert (await case.effects())["accounts"] == []


@pytest.mark.asyncio
async def test_foreign_remove_and_instagram_controls_reveal_no_account_details(
    social_case,
):
    case = social_case
    foreign = SocialEditorCase(type("Pg", (), {"url": case.engine.url})())
    try:
        await foreign.seed()
        await foreign.seed_account()
        response = await case.post(
            "remove", "telegram", extra=dict(account_id=str(foreign.account_id))
        )
        assert_error(response, 400, "social_account_owner_mismatch")
        assert len((await foreign.effects())["accounts"]) == 1
        response = await case.post(
            "remove",
            "telegram",
            extra=dict(account_id=str(uuid5(case.user.user_id, "instagram"))),
        )
        assert_error(response, 400, "social_instagram_verification_required")
        response = await case.post(
            "save",
            "telegram",
            extra=dict(network="instagram", url="https://instagram.com/other"),
        )
        assert_error(response, 400, "social_instagram_verification_required")
        absent = await case.post("remove", "telegram")
        assert absent.json() == dict(removed=False)
    finally:
        await foreign.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "defect",
    [
        "inactive",
        "nested",
        "pending",
        "dirty",
        "deleted",
        "wrong_user_bind",
        "wrong_profile_bind",
        "wrong_social_bind",
    ],
)
async def test_actual_session_metadata_defects_refuse_before_sql(
    social_case, defect
):
    case, factory = social_case, social_case.container.session_factory
    async with factory() as db:
        if defect != "inactive":
            await db.begin()
        if defect == "nested":
            await db.begin_nested()
        if defect == "pending":
            db.add(
                UserModel(
                    user_id=uuid4(),
                    telegram_id=str(uuid4()),
                    status="active",
                    messenger_type="telegram",
                )
            )
        if defect in ("dirty", "deleted"):
            user = await db.get(UserModel, case.user.user_id)
            if defect == "dirty":
                user.username = "pending"
            else:
                await db.delete(user)
        if defect.startswith("wrong_"):
            mapper = {
                "wrong_user_bind": UserModel,
                "wrong_profile_bind": BloggerProfileModel,
                "wrong_social_bind": SocialAccountModel,
            }[defect]
            db.sync_session.bind_mapper(mapper, case.engine.sync_engine)
        with (
            EditorTrace(case) as trace,
            pytest.raises(ValueError, match="^social_unavailable$"),
        ):
            await case.service.editor_repository.read_editor(
                case.user.user_id,
                principal=case.principal("telegram"),
                session=db,
            )
        assert trace.sql == []
        await db.rollback()


@pytest.mark.asyncio
async def test_wrong_uuid_and_missing_mixed_capability_refuse_before_sql(
    social_case,
):
    case = social_case
    with EditorTrace(case) as trace:
        with pytest.raises(ValueError, match="^financial_principal_changed$"):
            await case.service.editor_state(
                uuid4(), principal=case.principal("telegram")
            )
        for capability in (None, object()):
            service = replace(case.service, editor_repository=capability)
            with pytest.raises(ValueError, match="^social_unavailable$"):
                await service.editor_state(
                    case.user.user_id, principal=case.principal("telegram")
                )
        repository = replace(case.service.account_repo)
        service = replace(case.service, editor_repository=repository)
        with pytest.raises(ValueError, match="^social_unavailable$"):
            await service.editor_state(
                case.user.user_id, principal=case.principal("telegram")
            )
    assert trace.sql == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_actual_sql_editor_port_refuses_wrong_owner_or_uuid_only_proof(
    social_case, platform
):
    case = social_case
    wrong_owner = replace(case.principal(platform), user_id=uuid4())
    async with case.container.session_factory() as db, db.begin():
        with EditorTrace(case) as trace:
            for proof in (wrong_owner, case.user.user_id):
                with pytest.raises(
                    ValueError, match="^financial_principal_changed$"
                ):
                    await case.service.editor_repository.prepare_editor_write(
                        case.user.user_id, principal=proof, session=db
                    )
        assert trace.sql == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_stored_canonical_instagram_provenance_and_stored_id_guard(
    social_case, platform
):
    case, at = social_case, datetime.now(timezone.utc)
    # Explicit synthetic observation fixture, never external provider evidence.
    stable_id = "synthetic-" + uuid4().hex
    profile = replace(
        case.profile,
        instagram_user_id=stable_id,
        instagram_followers_count=0,
        instagram_stats_fetched_at=at,
    )
    stored = SocialAccount(
        account_id=uuid4(),
        user_id=case.user.user_id,
        platform=SocialPlatform.INSTAGRAM,
        url=profile.instagram_url,
        handle="synthetic",
        verified=True,
        external_id=stable_id,
        work_format=WorkFormat.UGC_ONLY,
        followers_count=0,
        metrics_source="synthetic_pg_fixture",
        metrics_fetched_at=at,
        verified_at=at,
        verification_observed_at=at,
        verification_source="synthetic_pg_fixture",
        created_at=at,
        updated_at=at,
    )
    async with case.factory.begin() as db:
        # The admitted profile writer takes User before profile/history. The
        # fixture social row is inserted under that same actual User barrier.
        await case.repos["blogger_repo"].save(profile, session=db)
        await case.service.account_repo.save(stored, session=db)
    with EditorTrace(case) as trace:
        response = await case.post("list", platform)
    assert response.status_code == 200, response.text
    trace.assert_read_only()
    (account,) = response.json()["accounts"]
    assert account["account_id"] == str(uuid5(case.user.user_id, "instagram"))
    assert account["verified"] is True
    assert account["external_id"] == stable_id
    assert account["followers_count"] == 0
    assert account["metrics_source"] == "synthetic_pg_fixture"
    assert account["verification_source"] == "synthetic_pg_fixture"
    for field in (
        "metrics_fetched_at",
        "verified_at",
        "verification_observed_at",
    ):
        assert datetime.fromisoformat(account[field]) == at
    assert response.json()["next_platform"] == "tiktok"
    with EditorTrace(case) as removal:
        denied = await case.post(
            "remove", platform, extra=dict(account_id=str(stored.account_id))
        )
    assert_error(denied, 400, "social_instagram_verification_required")
    removal.assert_user_first_write()
    assert len((await case.effects())["accounts"]) == 1


@pytest.mark.asyncio
async def test_actual_unavailable_schema_is_bounded_failure(social_case):
    case = social_case
    engine = case.container.session_factory.kw["bind"].sync_engine

    def hide_social_table(conn, cursor, statement, params, context, many):
        if statement.startswith("SET TRANSACTION"):
            # Existing actual root connection, no query result replacement and
            # no second transaction. Nonexistent private schema hides tables.
            conn.exec_driver_sql(
                'SET LOCAL search_path = "social_missing_fixture"'
            )

    event.listen(engine, "before_cursor_execute", hide_social_table)
    try:
        response = await case.post("list", "telegram")
        assert_error(response, 503, "social_unavailable")
    finally:
        event.remove(engine, "before_cursor_execute", hide_social_table)
    current = await case.post("list", "telegram")
    assert current.status_code == 200
