"""Prepared signed snapshot tests. Not collected/executed by source preparation.

All eventual evidence comes from real SQL, installed Container/main router and
existing producers. No SQL results or transaction capabilities are mocked.
"""

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from tests.helpers.native_snapshot_pg import (
    ActorGate,
    NativeSnapshotCase,
    SnapshotTrace,
    assert_error,
    evidence,
    finish_task,
)
from tests.postgres_financial.test_collaboration_persistence import (
    collaboration_pg as collaboration_pg,
)
from tests.postgres_financial.test_collaboration_persistence import start
from tests.postgres_financial.test_lifecycle_ledger_persistence import basis
from tests.postgres_financial.test_paid_selection_delivery import (
    delivery_env as delivery_env,
)
from tests.postgres_financial.test_paid_selection_interest import (
    capture,
    seed_creators,
    service,
)
from tests.postgres_financial.test_partner_view_api import (
    setup as partner_setup,
)
from tests.postgres_financial.test_selection_view_api import configuration
from tests.postgres_financial.test_v1_capture import capture_env as capture_env
from tests.postgres_financial.test_work_entitlement_runtime import start_flow
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.models import AdvertiserProfileModel
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)

__all__ = ["capture_env", "collaboration_pg", "delivery_env"]


@pytest.fixture(scope="session")
def native_snapshot_evidence():
    records = []
    yield records
    destination = os.environ.get("NATIVE_SNAPSHOT_EVIDENCE_PATH")
    if destination:
        Path(destination).write_text(json.dumps(records, indent=2) + "\n")


@pytest_asyncio.fixture
async def partner_snapshot(collaboration_pg):
    container, _, _ = await partner_setup(
        collaboration_pg, "client", "telegram"
    )
    factory, _, _, _, data = collaboration_pg
    case = NativeSnapshotCase(
        "partner", container, factory, data | {"foreign": data["creator"]}
    )
    try:
        await case.seed_actor()
        yield case
    finally:
        await case.dispose()


@pytest_asyncio.fixture
async def selection_snapshot(capture_env):
    env = capture_env
    creators = seed_creators(env)
    await capture(env)
    interest = await service(env).respond(env["order"], creators[0])
    assert interest.accepted
    case = NativeSnapshotCase(
        "selection",
        Container(configuration(env, enabled=False)),
        env["factory"],
        dict(
            client=env["client"],
            order=env["order"],
            creator=creators[0],
            second=creators[1],
            foreign=creators[2],
        ),
        env=env,
    )
    try:
        await case.seed_actor()
        yield case
    finally:
        await case.dispose()


@pytest_asyncio.fixture
async def summary_snapshot(capture_env, monkeypatch):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    case = NativeSnapshotCase(
        "summary",
        Container(configuration(env, enabled=False)),
        env["factory"],
        dict(
            client=env["client"],
            order=env["order"],
            creator=flow["creator"],
            manager=flow["manager"],
            foreign=flow["partner"],
        ),
        env=env,
        flow=flow,
    )
    try:
        await case.seed_actor()
        yield case
    finally:
        await case.dispose()
        await flow["container"].dispose()


@pytest.fixture(params=("partner", "selection", "summary"))
def native_snapshot(request):
    return request.getfixturevalue(request.param + "_snapshot")


@pytest.fixture
def scoped_snapshot(request):
    family, role = request.param
    return request.getfixturevalue(family + "_snapshot"), role


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("change", ["clear", "remap", "move"])
async def test_mapping_first_native_denial_precedes_private_reads(
    native_snapshot, platform, change, native_snapshot_evidence
):
    case, gate, task = native_snapshot, ActorGate("before"), None
    try:
        with SnapshotTrace(case, gate) as trace:
            task = asyncio.create_task(case.post(platform))
            reader = await asyncio.wait_for(gate.reached, 3)
            writer = await asyncio.wait_for(
                case.mutate_native(platform, change), 3
            )
            after_writer = await case.effects()
            gate.release.set()
            response = await asyncio.wait_for(task, 4)
        assert_error(response, 403, "financial_principal_changed")
        trace.assert_native_denied_before_private()
        assert await case.effects() == after_writer
        assert reader["pid"] != writer["pid"]
        native_snapshot_evidence.append(
            evidence(
                case, trace, writer["pid"], "mapping_first:" + change, platform
            )
        )
    finally:
        gate.release.set()
        await finish_task(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_snapshot_first_keeps_native_and_private_facts_coherent(
    native_snapshot, platform, native_snapshot_evidence
):
    case, gate, task = native_snapshot, ActorGate("after"), None
    try:
        with SnapshotTrace(case, gate) as trace:
            task = asyncio.create_task(case.post(platform))
            reader = await asyncio.wait_for(gate.reached, 3)
            # Writer must finish while reader is paused: no reader row lock.
            writer = await asyncio.wait_for(
                case.mutate_native(platform, private=True), 3
            )
            after_writer = await case.effects()
            gate.release.set()
            response = await asyncio.wait_for(task, 4)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        case.assert_old_private(response.json())
        trace.assert_read_only()
        assert await case.effects() == after_writer
        assert reader["pid"] != writer["pid"]
        with SnapshotTrace(case) as refreshed:
            fresh = await case.post(platform, external=writer["new_native"])
        assert fresh.status_code == 200, fresh.text
        case.assert_new_private(fresh.json())
        refreshed.assert_read_only()
        assert await case.effects() == after_writer
        native_snapshot_evidence.append(
            evidence(
                case,
                trace,
                writer["pid"],
                "snapshot_first:native_and_source",
                platform,
            )
        )
    finally:
        gate.release.set()
        await finish_task(task)


@pytest.mark.asyncio
async def test_snapshot_survives_slow_state_observer(
    partner_snapshot, native_snapshot_evidence, monkeypatch
):
    """A slow test observer must not abort the real read transaction."""
    original = partner_snapshot.effects
    first = True

    async def slow_effects():
        nonlocal first
        if first:
            first = False
            # Exceed the old gate timeout without faking SQL or HTTP results.
            await asyncio.sleep(5.2)
        return await original()

    monkeypatch.setattr(partner_snapshot, "effects", slow_effects)
    await test_snapshot_first_keeps_native_and_private_facts_coherent(
        partner_snapshot, "telegram", native_snapshot_evidence
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "status", ["active", "pause", "bot_blocked", "blocked", "deleted"]
)
async def test_current_snapshot_status_semantics_and_no_initialization(
    native_snapshot, platform, status
):
    case = native_snapshot
    await case.change_status(status)
    before = await case.effects()
    with SnapshotTrace(case) as trace:
        response = await case.post(platform)
    if status in ("blocked", "deleted"):
        code = {
            "partner": "partner_account_unavailable",
            "selection": "selection_client_inactive",
            "summary": "summary_actor_inactive",
        }[case.family]
        assert_error(response, 403, code)
    else:
        assert response.status_code == 200, response.text
    trace.assert_read_only()
    assert await case.effects() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("phase", ["before", "after"])
async def test_status_change_across_first_select_uses_one_snapshot(
    native_snapshot, platform, phase, native_snapshot_evidence
):
    case, gate, task = native_snapshot, ActorGate(phase), None
    try:
        with SnapshotTrace(case, gate) as trace:
            task = asyncio.create_task(case.post(platform))
            await asyncio.wait_for(gate.reached, 3)
            writer = await asyncio.wait_for(case.change_status("blocked"), 3)
            after_writer = await case.effects()
            gate.release.set()
            response = await asyncio.wait_for(task, 4)
        if phase == "before":
            code = {
                "partner": "partner_account_unavailable",
                "selection": "selection_client_inactive",
                "summary": "summary_actor_inactive",
            }[case.family]
            assert_error(response, 403, code)
        else:
            assert response.status_code == 200, response.text
        trace.assert_read_only()
        assert await case.effects() == after_writer
        native_snapshot_evidence.append(
            evidence(case, trace, writer, "status:" + phase, platform)
        )
    finally:
        gate.release.set()
        await finish_task(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_unknown_signed_identity_never_creates_user_country_or_wallet(
    native_snapshot, platform
):
    case = native_snapshot
    before = await case.effects()
    with SnapshotTrace(case) as trace:
        response = await case.post(
            platform, external=str(uuid4().int % 10**14 + 1)
        )
    assert_error(response, 404, "existing_financial_account_required")
    assert trace.snapshots == []
    trace.assert_read_only()
    assert all(
        "ORDER_ITEMS" not in row["sql"]
        and "FINANCIAL_WALLETS" not in row["sql"]
        and "USER_REFERRAL_BINDINGS" not in row["sql"]
        for row in trace.sql
    )
    assert await case.effects() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_existing_native_without_country_reads_without_filling_it(
    native_snapshot, platform
):
    case = native_snapshot
    before = await case.effects()
    assert before["actor"][2] is None
    with SnapshotTrace(case) as trace:
        response = await case.post(platform)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    trace.assert_read_only()
    assert await case.effects() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_foreign_order_or_public_actor_override_is_bounded(
    native_snapshot, platform
):
    case = native_snapshot
    before = await case.effects()
    with SnapshotTrace(case) as trace:
        response = await case.post(
            platform,
            order_id=uuid4(),
            extra={"actor_id": str(case.ids["foreign"])}
            if case.family == "partner"
            else None,
        )
    if case.family == "partner":
        assert_error(response, 422, "partner_request_invalid")
        assert trace.snapshots == []
    else:
        assert_error(
            response,
            404,
            "selection_order_not_found"
            if case.family == "selection"
            else "summary_not_found",
        )
    trace.assert_read_only()
    assert await case.effects() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_foreign_canonical_client_never_receives_original_order_data(
    selection_snapshot, platform
):
    case = selection_snapshot
    async with case.factory.begin() as db:
        db.add(
            AdvertiserProfileModel(
                user_id=case.ids["foreign"], contact="synthetic foreign"
            )
        )
    await case.seed_actor("foreign")
    before = await case.effects()
    with SnapshotTrace(case) as trace:
        response = await case.post(platform)
    assert_error(response, 404, "selection_order_not_found")
    assert str(case.ids["creator"]) not in response.text
    trace.assert_read_only()
    assert await case.effects() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_foreign_summary_actor_never_receives_original_work(
    summary_snapshot, platform
):
    case = summary_snapshot
    await case.seed_actor("foreign")
    before = await case.effects()
    with SnapshotTrace(case) as trace:
        response = await case.post(platform)
    assert_error(response, 404, "summary_not_found")
    trace.assert_read_only()
    assert await case.effects() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize(
    "scoped_snapshot",
    [("selection", "client"), ("summary", "client"), ("summary", "manager")],
    indirect=True,
)
async def test_current_role_membership_obeys_the_same_first_select_snapshot(
    scoped_snapshot, platform, phase, native_snapshot_evidence
):
    case, role = scoped_snapshot
    family = case.family
    await case.seed_actor(role)
    gate, task = ActorGate(phase), None
    try:
        with SnapshotTrace(case, gate) as trace:
            task = asyncio.create_task(case.post(platform))
            await asyncio.wait_for(gate.reached, 3)
            writer = await asyncio.wait_for(case.revoke_role(role), 3)
            after_writer = await case.effects()
            gate.release.set()
            response = await asyncio.wait_for(task, 4)
        if phase == "before":
            assert_error(
                response,
                403 if family == "selection" else 404,
                "selection_client_role_required"
                if family == "selection"
                else "summary_not_found",
            )
        else:
            assert response.status_code == 200, response.text
            if family == "summary":
                assert response.json()["role"] == role
                assert response.json()["total"] == (
                    2 if role == "client" else 1
                )
        trace.assert_read_only()
        assert await case.effects() == after_writer
        native_snapshot_evidence.append(
            evidence(
                case,
                trace,
                writer,
                "membership:" + role + ":" + phase,
                platform,
            )
        )
    finally:
        gate.release.set()
        await finish_task(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("phase", ["before", "after"])
async def test_partner_manager_assignment_visibility_retains_current_membership(
    partner_snapshot,
    collaboration_pg,
    platform,
    phase,
    native_snapshot_evidence,
):
    case = partner_snapshot
    await start(collaboration_pg)
    await case.seed_actor("manager")
    gate, task = ActorGate(phase), None
    try:
        with SnapshotTrace(case, gate) as trace:
            task = asyncio.create_task(case.post(platform))
            await asyncio.wait_for(gate.reached, 3)
            writer = await asyncio.wait_for(case.revoke_role("manager"), 3)
            after_writer = await case.effects()
            gate.release.set()
            response = await asyncio.wait_for(task, 4)
        assert response.status_code == 200, response.text
        assert len(response.json()["assignments"]["entries"]) == int(
            phase == "after"
        )
        trace.assert_read_only()
        assert await case.effects() == after_writer
        native_snapshot_evidence.append(
            evidence(case, trace, writer, "partner_manager:" + phase, platform)
        )
    finally:
        gate.release.set()
        await finish_task(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_partner_actual_historical_ledger_stays_private_and_read_only(
    partner_snapshot, collaboration_pg, platform
):
    case = partner_snapshot
    _, _, _, clock, data = collaboration_pg
    source = replace(
        await basis(collaboration_pg), reason="PRIVATE_NATIVE_SNAPSHOT_HISTORY"
    )
    async with case.factory.begin() as db:
        await FinancialLedgerService(
            SqlAlchemyFinancialLedgerRepository()
        ).issue(source, recorded_at=clock.at, session=db)
    before = await case.effects()
    with SnapshotTrace(case) as trace:
        response = await case.post(platform)
    assert response.status_code == 200, response.text
    finance = response.json()["financial"]
    assert finance["state"] == "ready"
    assert finance["balances"]["pending"] == "5000"
    assert finance["history"]["entries"][0]["order_id"] == str(data["order"])
    assert "PRIVATE_NATIVE_SNAPSHOT_HISTORY" not in response.text
    trace.assert_read_only()
    assert await case.effects() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_actual_contact_receipt_is_visible_without_becoming_work_success(
    delivery_env, platform
):
    env = delivery_env
    attempt = await env["worker"].prepare(env["interest"].job_id)
    assert attempt is not None
    await env["worker"].deliver(attempt)
    assert len(env["bot"].calls) == 1
    case = NativeSnapshotCase(
        "selection",
        Container(configuration(env, enabled=False)),
        env["factory"],
        dict(
            client=env["client"],
            order=env["order"],
            creator=env["creator"],
            foreign=env["other_creator"],
        ),
        env=env,
    )
    try:
        await case.seed_actor()
        before = await case.effects()
        with SnapshotTrace(case) as trace:
            response = await case.post(platform)
        assert response.status_code == 200, response.text
        position = response.json()["positions"][0]
        assert position["delivery_state"] == "accepted"
        assert position["deliveries"][0]["assignment_id"] == str(
            env["interest"].assignment_id
        )
        assert "provider_reference" not in response.text
        trace.assert_read_only()
        assert await case.effects() == before
    finally:
        await case.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_legacy_summary_uses_real_interaction_without_v1_outcome(
    summary_snapshot, platform
):
    case = summary_snapshot
    await case.seed_legacy_summary()
    before = await case.effects()
    with SnapshotTrace(case) as trace:
        response = await case.post(platform)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["source"] == "legacy_feedback"
    assert data["total"] == 1
    assert data["states"] == {"legacy_pending": 1}
    assert data["contact_accepted"] is None
    assert "creator_id" not in response.text
    trace.assert_read_only()
    assert await case.effects() == before
