"""Real SQL legacy confirmation, attachment lifetime and two-backend races.

Only collect/run after the root grants the isolated PostgreSQL slot. Provider
responses are synthetic; repositories, transactions, statements and locks are
the installed SQL implementations.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, event, select, text, update

from tests.postgres_financial.legacy_confirmation_support import (
    ObservedConfirmationTransaction,
    assert_barrier_order,
    backend_pid,
    confirmation_case,
    finish_tasks,
    observe_confirmation_sql,
    profile_fact,
    user_fact,
    wait_for_blocker,
)
from ugc_bot.application.services.instagram_verification_service import (
    VerificationApiUnavailable,
    VerificationLinkConflict,
    VerificationLinkSuccess,
    VerificationLinkUnavailable,
    VerificationMismatch,
    VerificationSuccess,
    VerificationUnavailable,
)
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    InstagramVerificationCodeModel,
    UserModel,
)


@pytest_asyncio.fixture
async def legacy_confirmation_pg(financial_pg_engine):
    async with confirmation_case(financial_pg_engine) as case:
        yield case


@pytest.fixture(scope="session")
def legacy_confirmation_evidence():
    records = []
    yield records
    path = os.environ.get("LEGACY_MAX_SQL_EVIDENCE_PATH")
    if path:
        Path(path).write_text(json.dumps(records, indent=2) + "\n")


async def prepare(case, db, code):
    return await case.repos["user_repo"].prepare_legacy_max_attachment(
        case.target.user_id,
        code_id=code.code_id,
        max_id=code.link_max_id,
        max_chat_id=code.link_max_chat_id,
        session=db,
    )


async def attachment_setup(case, scenario, *, owner_before=None):
    requested = "max_" + uuid4().hex
    metadata = dict(
        link_max_id=requested,
        link_max_chat_id="initiating_chat",
        link_username="must not replace canonical name",
        link_phone="+7 777 123 45 67",
    )
    owner = None
    if scenario == "separate":
        owner_id = (
            UUID(int=case.target.user_id.int + (-1 if owner_before else 1))
            if owner_before is not None
            else uuid4()
        )
        owner = user_fact(user_id=owner_id, max_id=requested)
        await case.seed(
            owner, profile_fact(owner, phone="owner phone", confirmed=True)
        )
    elif scenario in ("same", "target_bound"):
        native = requested if scenario == "same" else "occupied_" + uuid4().hex
        async with case.factory.begin() as db:
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == case.target.user_id)
                .values(max_id=native, max_chat_id="original_chat")
            )
    elif scenario == "no_link":
        metadata = {}
    elif scenario == "missing_service":
        case.service.user_role_service = None
    elif scenario == "invalid_native":
        metadata["link_max_id"] = "invalid/native"
    elif scenario == "invalid_chat":
        metadata["link_max_chat_id"] = "invalid/chat"
    return await case.code(**metadata), owner


def assert_confirmed(facts, case, code, mode):
    assert facts["code"][0]["used"]
    assert facts["profile"][0]["confirmed"]
    expected_id = (
        case.profile.instagram_user_id if mode == "manual" else case.sender
    )
    assert facts["profile"][0]["instagram_user_id"] == expected_id
    social = facts["social"]
    assert len(social) == 1
    assert social[0]["external_id"] == expected_id
    assert social[0]["verified"]
    source = "manual_code" if mode == "manual" else "instagram_webhook"
    assert social[0]["verification_source"] == source
    assert (social[0]["verified_at"] is None) is (mode == "manual")
    proof = [row for row in facts["history"] if row["source"] == source]
    assert proof
    assert proof[-1]["active"]
    assert proof[-1]["fact_at"] is not None
    assert str(code.code_id) in proof[-1]["business_key"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
@pytest.mark.parametrize(
    "scenario",
    [
        "unused",
        "same",
        "separate",
        "target_bound",
        "no_link",
        "missing_service",
        "invalid_native",
        "invalid_chat",
    ],
)
async def test_configured_sql_confirmation_keeps_attachment_outcomes_explicit(
    legacy_confirmation_pg, mode, scenario
):
    case = legacy_confirmation_pg
    code, owner = await attachment_setup(case, scenario)
    before = await case.facts(code)
    owner_before = (
        await case.facts(code, user_id=owner.user_id) if owner else None
    )
    result = await case.confirm(mode, code)
    after = await case.facts(code)
    assert_confirmed(after, case, code, mode)
    expected_user = dict(before["user"][0])
    if scenario == "unused":
        assert isinstance(result, VerificationLinkSuccess)
        expected_user.update(
            max_id=code.link_max_id, max_chat_id=code.link_max_chat_id
        )
        assert after["profile"][0]["phone"] == code.link_phone
    elif scenario == "same":
        assert isinstance(result, VerificationLinkSuccess)
        assert after["profile"][0]["phone"] is None
    elif scenario in ("separate", "target_bound"):
        assert isinstance(result, VerificationLinkConflict)
        assert after["profile"][0]["phone"] is None
    elif scenario == "no_link":
        assert (
            result is True
            if mode == "manual"
            else isinstance(result, VerificationSuccess)
        )
    else:
        assert isinstance(result, VerificationLinkUnavailable)
    assert after["user"] == [expected_user]
    if owner:
        owner_after = await case.facts(code, user_id=owner.user_id)
        for name in ("user", "profile", "history", "social"):
            assert owner_after[name] == owner_before[name]
    replay = await case.confirm(mode, code)
    assert replay is False if mode == "manual" else replay is None
    assert await case.facts(code) == after


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
@pytest.mark.parametrize("owner_before", [False, True])
async def test_actual_confirmation_acquires_complete_sorted_users_first(
    legacy_confirmation_pg, mode, owner_before
):
    case = legacy_confirmation_pg
    code, owner = await attachment_setup(
        case, "separate", owner_before=owner_before
    )
    case.service.transaction_manager = ObservedConfirmationTransaction(
        case.transactions, mode
    )
    async with observe_confirmation_sql(case) as records:
        result = await case.confirm(mode, code)
    assert isinstance(result, VerificationLinkConflict)
    assert_barrier_order(records, (case.target.user_id, owner.user_id))
    assert len({row["pid"] for row in records}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
async def test_no_metadata_confirmation_still_locks_its_target(
    legacy_confirmation_pg, mode
):
    case = legacy_confirmation_pg
    code = await case.code()
    case.service.transaction_manager = ObservedConfirmationTransaction(
        case.transactions, mode
    )
    async with observe_confirmation_sql(case) as records:
        await case.confirm(mode, code)
    assert_barrier_order(records, (case.target.user_id,), native=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ["unused", "same", "separate", "target_bound"]
)
async def test_direct_legacy_wrapper_uses_actual_sql_narrow_attachment(
    legacy_confirmation_pg, scenario
):
    case = legacy_confirmation_pg
    code, owner = await attachment_setup(case, scenario)
    before = await case.facts(code)
    role = case.service.user_role_service
    role.transaction_manager = ObservedConfirmationTransaction(
        case.transactions, "manual"
    )
    async with observe_confirmation_sql(case) as records:
        result = await role.link_max_account(
            code.link_max_id,
            case.profile.instagram_url,
            "must not replace canonical name",
            max_chat_id=code.link_max_chat_id,
        )
    expected = {
        "unused": "ready",
        "same": "same_account",
        "separate": "conflict",
        "target_bound": "conflict",
    }
    assert result.state == expected[scenario]
    after = await case.facts(code)
    expected_user = dict(before["user"][0])
    if scenario == "unused":
        expected_user.update(
            max_id=code.link_max_id, max_chat_id=code.link_max_chat_id
        )
    assert after["user"] == [expected_user]
    for name in ("profile", "code", "history", "social"):
        assert after[name] == before[name]
    scope = (case.target.user_id,) + ((owner.user_id,) if owner else ())
    assert_barrier_order(records, scope, confirmed=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["commit", "rollback"])
async def test_actual_same_session_new_root_rejects_expired_preparation(
    legacy_confirmation_pg, ending
):
    case = legacy_confirmation_pg
    code, _ = await attachment_setup(case, "unused")
    before = await case.facts(code)
    async with case.factory() as db:
        await db.begin()
        preparation = await prepare(case, db, code)
        assert preparation.protected
        first = db.sync_session.get_transaction()
        await getattr(db, ending)()
        await db.begin()
        assert db.sync_session.get_transaction() is not first
        connection = await db.connection()
        connection.info["legacy_confirmation_reader"] = await backend_pid(db)
        try:
            async with observe_confirmation_sql(case) as records:
                result = await case.repos["user_repo"].attach_prepared_max(
                    preparation, session=db
                )
            assert result.state == "unavailable"
            assert records == []
        finally:
            connection.info.pop("legacy_confirmation_reader", None)
        await db.commit()
    assert await case.facts(code) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["commit", "rollback"])
async def test_actual_enclosing_savepoint_preparation_is_unavailable(
    legacy_confirmation_pg, ending
):
    case = legacy_confirmation_pg
    code, _ = await attachment_setup(case, "unused")
    before = await case.facts(code)
    async with case.factory.begin() as db:
        connection = await db.connection()
        connection.info["legacy_confirmation_reader"] = await backend_pid(db)
        try:
            nested = await db.begin_nested()
            async with observe_confirmation_sql(case) as records:
                preparation = await prepare(case, db, code)
                await getattr(nested, ending)()
                result = await case.repos["user_repo"].attach_prepared_max(
                    preparation, session=db
                )
            assert not preparation.protected
            assert preparation.reason == "nested_transaction_unavailable"
            assert result.state == "unavailable"
            assert records == []
        finally:
            connection.info.pop("legacy_confirmation_reader", None)
    assert await case.facts(code) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["commit", "rollback"])
async def test_actual_root_preparation_survives_later_and_own_savepoints(
    legacy_confirmation_pg, ending
):
    case = legacy_confirmation_pg
    code, _ = await attachment_setup(case, "unused")
    async with case.factory.begin() as db:
        preparation = await prepare(case, db, code)
        root = db.sync_session.get_transaction()
        nested = await db.begin_nested()
        await getattr(nested, ending)()
        attached = await case.repos["user_repo"].attach_prepared_max(
            preparation, session=db
        )
        assert attached.state == "ready"
        assert attached.reason == "attached"
        assert db.sync_session.get_transaction() is root
        assert root.is_active
        again = await case.repos["user_repo"].attach_prepared_max(
            preparation, session=db
        )
        assert again.state == "same_account"
    facts = await case.facts(code)
    assert facts["user"][0]["max_id"] == code.link_max_id
    assert not facts["code"][0]["used"]
    assert not facts["profile"][0]["confirmed"]


def changed_native(change):
    return None if change == "clear" else "changed_" + uuid4().hex


async def change_user(db, uid, field, value):
    await db.execute(
        update(UserModel).where(UserModel.user_id == uid).values({field: value})
    )


def record_wait(evidence, label, mode, reader, writer, **details):
    assert reader != writer
    evidence.append(
        {
            "case": label,
            "mode": mode,
            "reader_pid": reader,
            "writer_pid": writer,
            "distinct_backends": True,
            **details,
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
@pytest.mark.parametrize("field", ["telegram_id", "max_id"])
@pytest.mark.parametrize("change", ["clear", "remap"])
async def test_mapping_commit_before_user_barrier_is_fresh_and_never_detached(
    legacy_confirmation_pg, legacy_confirmation_evidence, mode, field, change
):
    case = legacy_confirmation_pg
    code, owner = await attachment_setup(case, "separate")
    before = await case.facts(code)
    owner_before = await case.facts(code, user_id=owner.user_id)
    started = asyncio.Future()
    manager = ObservedConfirmationTransaction(
        case.transactions, mode, started=started
    )
    case.service.transaction_manager = manager
    value = changed_native(change)
    task = None
    async with (
        observe_confirmation_sql(case) as records,
        case.factory.begin() as writer,
    ):
        writer_pid = await backend_pid(writer)
        await change_user(writer, owner.user_id, field, value)
        task = asyncio.create_task(case.confirm(mode, code))
        try:
            reader_pid = await asyncio.wait_for(started, 2)
            assert reader_pid != writer_pid
            await wait_for_blocker(writer, reader_pid, writer_pid)
            assert not task.done()
            assert all(row["kind"] == "user" for row in records)
            await writer.commit()
            result = await asyncio.wait_for(task, 3)
        finally:
            await writer.rollback()
            await finish_tasks(task)
    expected = (
        VerificationUnavailable
        if field == "max_id"
        else (VerificationLinkConflict)
    )
    assert isinstance(result, expected)
    assert_barrier_order(
        records,
        (case.target.user_id, owner.user_id),
        confirmed=field == "telegram_id",
    )
    after = await case.facts(code)
    assert after["user"] == before["user"]
    assert after["profile"][0]["phone"] is None
    if field == "max_id":
        assert result.reason == "native_scope_changed"
        for name in ("profile", "code", "history", "social"):
            assert after[name] == before[name]
    else:
        assert_confirmed(after, case, code, mode)
    owner_after = await case.facts(code, user_id=owner.user_id)
    expected_owner = dict(owner_before["user"][0])
    expected_owner[field] = value
    assert owner_after["user"] == [expected_owner]
    for name in ("profile", "history", "social"):
        assert owner_after[name] == owner_before[name]
    record_wait(
        legacy_confirmation_evidence,
        "mapping_first",
        mode,
        reader_pid,
        writer_pid,
        field=field,
        change=change,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
@pytest.mark.parametrize("field", ["telegram_id", "max_id"])
@pytest.mark.parametrize("change", ["clear", "remap"])
async def test_confirmation_user_barriers_hold_later_mapping_until_commit(
    legacy_confirmation_pg, legacy_confirmation_evidence, mode, field, change
):
    case = legacy_confirmation_pg
    code, owner = await attachment_setup(case, "separate")
    completed, writer_started = asyncio.Future(), asyncio.Future()
    release = asyncio.Event()
    case.service.transaction_manager = ObservedConfirmationTransaction(
        case.transactions, mode, completed=completed, release=release
    )
    value = changed_native(change)

    async def mapping_writer():
        async with case.factory.begin() as writer:
            writer_pid = await backend_pid(writer)
            writer_started.set_result(writer_pid)
            await change_user(writer, owner.user_id, field, value)
        return writer_pid

    confirmation, writer = None, None
    async with observe_confirmation_sql(case) as records:
        confirmation = asyncio.create_task(case.confirm(mode, code))
        try:
            reader_pid = await asyncio.wait_for(completed, 2)
            writer = asyncio.create_task(mapping_writer())
            writer_pid = await asyncio.wait_for(writer_started, 2)
            assert reader_pid != writer_pid
            async with case.factory.begin() as observer:
                await wait_for_blocker(observer, writer_pid, reader_pid)
            assert not writer.done()
            assert not confirmation.done()
            release.set()
            result = await asyncio.wait_for(confirmation, 3)
            await asyncio.wait_for(writer, 3)
        finally:
            release.set()
            await finish_tasks(confirmation, writer)
    assert isinstance(result, VerificationLinkConflict)
    assert_barrier_order(records, (case.target.user_id, owner.user_id))
    facts = await case.facts(code)
    assert_confirmed(facts, case, code, mode)
    assert facts["user"][0]["max_id"] is None
    owner_facts = await case.facts(code, user_id=owner.user_id)
    assert owner_facts["user"][0][field] == value
    assert owner_facts["user"][0]["admin"]
    assert owner_facts["user"][0]["issue_count"] == 7
    record_wait(
        legacy_confirmation_evidence,
        "confirmation_first",
        mode,
        reader_pid,
        writer_pid,
        field=field,
        change=change,
    )


def changed_fact_statement(case, code, change, other):
    code_row = InstagramVerificationCodeModel
    profile = BloggerProfileModel
    code_where = code_row.code_id == code.code_id
    profile_where = profile.user_id == case.target.user_id
    statements = {
        "code_used": update(code_row).where(code_where).values(used=True),
        "code_expired": update(code_row)
        .where(code_where)
        .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)),
        "code_owner": update(code_row)
        .where(code_where)
        .values(user_id=other.user_id),
        "code_uuid": update(code_row).where(code_where).values(code_id=uuid4()),
        "code_metadata": update(code_row)
        .where(code_where)
        .values(link_max_id="different_" + uuid4().hex),
        "profile_missing": delete(profile).where(profile_where),
        "target_missing": delete(UserModel).where(
            UserModel.user_id == case.target.user_id
        ),
        "profile_phone": update(profile)
        .where(profile_where)
        .values(phone="current profile phone"),
        "profile_handle": update(profile)
        .where(profile_where)
        .values(
            instagram_url="https://instagram.com/changed_" + uuid4().hex[:16],
            instagram_username="changed_" + uuid4().hex[:16],
        ),
    }
    return statements[change]


async def change_before_user_barrier(case, code, mode, change):
    other = user_fact()
    await case.seed(other)
    started = asyncio.Future()
    case.service.transaction_manager = ObservedConfirmationTransaction(
        case.transactions, mode, started=started
    )
    task = None
    async with case.factory.begin() as writer:
        writer_pid = await backend_pid(writer)
        await writer.execute(
            select(UserModel.user_id)
            .where(UserModel.user_id == case.target.user_id)
            .with_for_update(key_share=True)
        )
        await writer.execute(changed_fact_statement(case, code, change, other))
        task = asyncio.create_task(case.confirm(mode, code))
        try:
            reader_pid = await asyncio.wait_for(started, 2)
            assert reader_pid != writer_pid
            await wait_for_blocker(writer, reader_pid, writer_pid)
            assert not task.done()
            await writer.commit()
            result = await asyncio.wait_for(task, 3)
        finally:
            await writer.rollback()
            await finish_tasks(task)
    return result, reader_pid, writer_pid


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
@pytest.mark.parametrize(
    "change",
    [
        "code_used",
        "code_expired",
        "code_owner",
        "code_uuid",
        "code_metadata",
        "profile_missing",
        "target_missing",
    ],
)
async def test_post_wait_code_target_and_profile_facts_prevent_confirmation(
    legacy_confirmation_pg, legacy_confirmation_evidence, mode, change
):
    case = legacy_confirmation_pg
    code, _ = await attachment_setup(case, "unused")
    result, reader, writer = await change_before_user_barrier(
        case, code, mode, change
    )
    assert (
        result is False
        or result is None
        or isinstance(result, VerificationUnavailable)
    )
    facts = await case.facts(code)
    assert facts["social"] == []
    assert not any(row["confirmed"] for row in facts["profile"])
    assert not any(row["max_id"] for row in facts["user"])
    assert not any(
        row["source"] in ("manual_code", "instagram_webhook")
        for row in facts["history"]
    )
    if facts["code"]:
        assert facts["code"][0]["used"] is (change == "code_used")
    record_wait(
        legacy_confirmation_evidence,
        "post_wait_fact",
        mode,
        reader,
        writer,
        change=change,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
@pytest.mark.parametrize("change", ["profile_phone", "profile_handle"])
async def test_current_profile_after_wait_controls_proof_and_phone(
    legacy_confirmation_pg, legacy_confirmation_evidence, mode, change
):
    case = legacy_confirmation_pg
    code, _ = await attachment_setup(case, "unused")
    result, reader, writer = await change_before_user_barrier(
        case, code, mode, change
    )
    facts = await case.facts(code)
    if change == "profile_handle" and mode == "webhook":
        assert isinstance(result, VerificationMismatch)
        assert not facts["code"][0]["used"]
        assert not facts["profile"][0]["confirmed"]
        assert facts["social"] == []
        assert facts["user"][0]["max_id"] is None
    else:
        assert isinstance(result, VerificationLinkSuccess)
        assert_confirmed(facts, case, code, mode)
        expected_phone = (
            "current profile phone"
            if change == "profile_phone"
            else code.link_phone
        )
        assert facts["profile"][0]["phone"] == expected_phone
    record_wait(
        legacy_confirmation_evidence,
        "fresh_profile",
        mode,
        reader,
        writer,
        change=change,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["user", "code", "profile"])
async def test_actual_caller_session_refreshes_strongly_cached_current_facts(
    legacy_confirmation_pg, legacy_confirmation_evidence, changed
):
    case = legacy_confirmation_pg
    code, _ = await attachment_setup(case, "unused")
    async with case.transactions.transaction() as reader:
        reader_pid = await backend_pid(reader)
        cached = [
            await reader.get(UserModel, case.target.user_id),
            await reader.get(InstagramVerificationCodeModel, code.code_id),
            await reader.get(BloggerProfileModel, case.target.user_id),
        ]

        class ActualCallerTransaction:
            @asynccontextmanager
            async def transaction(self):
                # The real outer SessionTransactionManager owns this root.
                assert reader.in_transaction()
                yield reader

        async with case.factory.begin() as writer:
            writer_pid = await backend_pid(writer)
            statements = {
                "user": update(UserModel)
                .where(UserModel.user_id == case.target.user_id)
                .values(max_id="current_" + uuid4().hex),
                "code": update(InstagramVerificationCodeModel)
                .where(InstagramVerificationCodeModel.code_id == code.code_id)
                .values(link_max_chat_id="current_chat"),
                "profile": update(BloggerProfileModel)
                .where(BloggerProfileModel.user_id == case.target.user_id)
                .values(phone="current phone"),
            }
            await writer.execute(statements[changed])
        case.service.transaction_manager = ActualCallerTransaction()
        result = await case.confirm("manual", code)
        if changed == "code":
            assert isinstance(result, VerificationUnavailable)
            assert result.reason == "verification_scope_changed"
            assert cached[1].link_max_chat_id == "current_chat"
        elif changed == "user":
            assert isinstance(result, VerificationLinkConflict)
            assert cached[0].max_id.startswith("current_")
        else:
            assert isinstance(result, VerificationLinkSuccess)
            assert cached[2].phone == "current phone"
    facts = await case.facts(code)
    if changed == "code":
        assert not facts["code"][0]["used"]
        assert not facts["profile"][0]["confirmed"]
        assert facts["social"] == []
    else:
        assert_confirmed(facts, case, code, "manual")
        if changed == "profile":
            assert facts["profile"][0]["phone"] == "current phone"
    record_wait(
        legacy_confirmation_evidence,
        "strong_orm_cache",
        "manual",
        reader_pid,
        writer_pid,
        changed=changed,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
async def test_code_expiring_while_current_profile_waits_is_not_consumed(
    legacy_confirmation_pg, legacy_confirmation_evidence, mode
):
    case = legacy_confirmation_pg
    code, _ = await attachment_setup(case, "unused")
    deadline = datetime.now(timezone.utc) + timedelta(seconds=1)
    async with case.factory.begin() as db:
        await db.execute(
            update(InstagramVerificationCodeModel)
            .where(InstagramVerificationCodeModel.code_id == code.code_id)
            .values(expires_at=deadline)
        )
    before = await case.facts(code)
    started = asyncio.Future()
    case.service.transaction_manager = ObservedConfirmationTransaction(
        case.transactions, mode, started=started
    )
    task = None
    async with (
        observe_confirmation_sql(case) as records,
        case.factory.begin() as writer,
    ):
        writer_pid = await backend_pid(writer)
        await writer.execute(
            select(BloggerProfileModel.user_id)
            .where(BloggerProfileModel.user_id == case.target.user_id)
            .with_for_update()
        )
        task = asyncio.create_task(case.confirm(mode, code))
        try:
            reader_pid = await asyncio.wait_for(started, 2)
            await wait_for_blocker(writer, reader_pid, writer_pid)
            assert [row["kind"] for row in records][-3:] == [
                "code",
                "history",
                "profile",
            ]
            assert not task.done()
            for _ in range(200):
                if await writer.scalar(
                    text("SELECT clock_timestamp() >= :deadline"),
                    {"deadline": deadline},
                ):
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("bounded database expiry wait did not finish")
            await writer.commit()
            result = await asyncio.wait_for(task, 3)
        finally:
            await writer.rollback()
            await finish_tasks(task)
    assert result is False if mode == "manual" else result is None
    assert await case.facts(code) == before
    assert_barrier_order(records, (case.target.user_id,))
    record_wait(
        legacy_confirmation_evidence,
        "expiry_after_code_lock",
        mode,
        reader_pid,
        writer_pid,
    )


@pytest.mark.asyncio
async def test_direct_wrapper_keeps_frozen_target_after_handle_transfer(
    legacy_confirmation_pg, legacy_confirmation_evidence
):
    case = legacy_confirmation_pg
    code, _ = await attachment_setup(case, "unused")
    other = user_fact()
    other_profile = profile_fact(other, phone="other original phone")
    await case.seed(other, other_profile)
    started = asyncio.Future()
    role = case.service.user_role_service
    role.transaction_manager = ObservedConfirmationTransaction(
        case.transactions, "manual", started=started
    )
    task = None
    async with (
        observe_confirmation_sql(case) as records,
        case.factory.begin() as writer,
    ):
        writer_pid = await backend_pid(writer)
        await writer.execute(
            select(UserModel.user_id)
            .where(UserModel.user_id == case.target.user_id)
            .with_for_update(key_share=True)
        )
        await writer.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == case.target.user_id)
            .values(
                instagram_url="https://instagram.com/changed_"
                + uuid4().hex[:16],
                instagram_username="changed_" + uuid4().hex[:16],
            )
        )
        await writer.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == other.user_id)
            .values(
                instagram_url=case.profile.instagram_url,
                instagram_username=case.profile.instagram_username,
            )
        )
        task = asyncio.create_task(
            role.link_max_account(
                code.link_max_id,
                case.profile.instagram_url,
                "new name",
                max_chat_id=code.link_max_chat_id,
            )
        )
        try:
            reader_pid = await asyncio.wait_for(started, 2)
            await wait_for_blocker(writer, reader_pid, writer_pid)
            await writer.commit()
            result = await asyncio.wait_for(task, 3)
        finally:
            await writer.rollback()
            await finish_tasks(task)
    assert result.state == "unavailable"
    assert result.reason == "target_profile_changed"
    assert_barrier_order(records, (case.target.user_id,), confirmed=False)
    target_facts = await case.facts(code)
    other_facts = await case.facts(code, user_id=other.user_id)
    assert target_facts["user"][0]["max_id"] is None
    assert other_facts["user"][0]["max_id"] is None
    assert other_facts["profile"][0]["phone"] == other_profile.phone
    assert other_facts["profile"][0]["instagram_url"] == (
        case.profile.instagram_url
    )
    record_wait(
        legacy_confirmation_evidence,
        "direct_frozen_target",
        "direct",
        reader_pid,
        writer_pid,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing", ["client", "blank_actual", "username_only", "blank_expected"]
)
async def test_actual_sql_sender_without_external_profile_proof_keeps_code(
    legacy_confirmation_pg, missing
):
    case = legacy_confirmation_pg
    code, _ = await attachment_setup(case, "unused")

    class UsernameOnly:
        async def get_profile_by_id(self, sender):
            return None

        async def get_username_by_id(self, sender):
            return case.profile.instagram_username

    if missing == "client":
        case.service.instagram_api_client = None
    elif missing == "blank_actual":
        case.api.username_map[case.sender] = "   "
    elif missing == "username_only":
        case.service.instagram_api_client = UsernameOnly()
    else:
        async with case.factory.begin() as db:
            await db.execute(
                update(BloggerProfileModel)
                .where(BloggerProfileModel.user_id == case.target.user_id)
                .values(instagram_url="", instagram_username="")
            )
    before = await case.facts(code)
    result = await case.confirm("webhook", code)
    assert isinstance(result, VerificationApiUnavailable)
    assert await case.facts(code) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
async def test_actual_uniqueness_savepoint_retains_valid_confirmation(
    legacy_confirmation_pg,
    financial_pg_engine,
    legacy_confirmation_evidence,
    mode,
):
    case = legacy_confirmation_pg
    code, _ = await attachment_setup(case, "unused")
    other = user_fact()
    await case.seed(other)
    manager = ObservedConfirmationTransaction(case.transactions, mode)
    case.service.transaction_manager = manager
    engine = case.factory.kw["bind"].sync_engine
    writer_pids, errors = [], []

    def win_native_race(conn, cursor, statement, parameters, context, many):
        if (
            writer_pids
            or not conn.info.get("legacy_confirmation_reader")
            or not statement.startswith("UPDATE users SET")
            or "RETURNING" not in statement
        ):
            return
        # The other ordinary SQL writer commits after the real owner re-read
        # and before the real conditional UPDATE; no SQL response is mocked.
        with financial_pg_engine.begin() as writer:
            writer.execute(text("SET LOCAL lock_timeout='3s'"))
            writer.execute(text("SET LOCAL statement_timeout='4s'"))
            writer_pids.append(writer.scalar(text("SELECT pg_backend_pid()")))
            writer.execute(
                update(UserModel)
                .where(UserModel.user_id == other.user_id)
                .values(max_id=code.link_max_id)
            )

    def real_unique_error(context):
        state = getattr(context.original_exception, "sqlstate", None)
        if state == "23505":
            errors.append(state)

    event.listen(engine, "before_cursor_execute", win_native_race)
    event.listen(engine, "handle_error", real_unique_error)
    try:
        result = await case.confirm(mode, code)
    finally:
        event.remove(engine, "before_cursor_execute", win_native_race)
        event.remove(engine, "handle_error", real_unique_error)
    assert isinstance(result, VerificationLinkConflict)
    assert result.reason == "native_identity_taken"
    assert errors == ["23505"]
    facts = await case.facts(code)
    assert_confirmed(facts, case, code, mode)
    assert facts["user"][0]["max_id"] is None
    assert facts["profile"][0]["phone"] is None
    other_facts = await case.facts(code, user_id=other.user_id)
    assert other_facts["user"][0]["max_id"] == code.link_max_id
    assert other_facts["user"][0]["admin"]
    record_wait(
        legacy_confirmation_evidence,
        "real_unique_constraint",
        mode,
        manager.reader_pid,
        writer_pids[0],
        sqlstate=errors[0],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "webhook"])
@pytest.mark.parametrize("failure", ["social", "consume", "attach"])
async def test_unexpected_post_confirmation_failure_rolls_back_all_sql_facts(
    legacy_confirmation_pg, mode, failure
):
    case = legacy_confirmation_pg
    code, _ = await attachment_setup(case, "unused")
    before = await case.facts(code)
    case.service.transaction_manager = ObservedConfirmationTransaction(
        case.transactions, mode
    )
    engine = case.factory.kw["bind"].sync_engine
    target = {
        "social": "INSERT INTO creator_social_accounts",
        "consume": "UPDATE instagram_verification_codes SET",
        "attach": "UPDATE users SET",
    }[failure]
    fired = []

    def unexpected_after_write(
        conn, cursor, statement, parameters, context, many
    ):
        if (
            not fired
            and conn.info.get("legacy_confirmation_reader")
            and statement.startswith(target)
        ):
            fired.append(failure)
            raise RuntimeError("synthetic post-confirmation failure")

    event.listen(engine, "after_cursor_execute", unexpected_after_write)
    try:
        with pytest.raises(
            RuntimeError, match="^synthetic post-confirmation failure$"
        ):
            await case.confirm(mode, code)
    finally:
        event.remove(engine, "after_cursor_execute", unexpected_after_write)
    assert fired == [failure]
    assert await case.facts(code) == before
