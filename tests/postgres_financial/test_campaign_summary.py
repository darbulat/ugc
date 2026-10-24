"""Own campaign aggregates distinguish contact acceptance and work facts."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.orm import Session

from tests.postgres_financial.test_paid_selection_delivery import (
    delivery_env as _delivery_env,
)
from tests.postgres_financial.test_selection_view_api import (
    app,
    configuration,
    identity,
    signed,
)
from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from tests.postgres_financial.test_work_entitlement_runtime import (
    finish_work,
    start_flow,
)
from ugc_bot.application.services.campaign_summary_service import (
    CampaignSummaryService,
)
from ugc_bot.container import Container
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.collaboration_models import CollaborationModel
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    ManagerOrderModel,
    OfferDispatchModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.campaign_summary import (
    SqlAlchemyCampaignSummaryRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager

capture_env = _capture_env
delivery_env = _delivery_env


def service(env):
    return CampaignSummaryService(
        SqlAlchemyCampaignSummaryRepository(),
        SessionTransactionManager(env["factory"]),
        SystemClock(),
    )


@pytest.mark.asyncio
async def test_summary_uses_current_scope_and_immutable_work_result(
    capture_env, monkeypatch
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    try:
        summary = service(env)
        client = await summary.view(env["order"], env["client"])
        assert client["source"] == "financial_positions"
        assert client["role"] == "client"
        assert client["total"] == 2
        assert client["states"] == {"assigned": 1, "unassigned": 1}
        assert client["contact_accepted"] == 0
        manager = await summary.view(env["order"], flow["manager"])
        assert manager["total"] == 1
        assert manager["states"] == {"assigned": 1}
        assert "creator_id" not in repr(manager)
        with pytest.raises(LookupError, match="summary_not_found"):
            await summary.view(env["order"], flow["partner"])

        await finish_work(env, flow)
        final = await summary.view(env["order"], env["client"])
        assert final["states"] == {"success_final": 1, "unassigned": 1}
        assert final["contact_accepted"] == 0

        # A mutable state column cannot invent a paid/publication outcome.
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(CollaborationModel)
                .where(CollaborationModel.assignment_id == flow["assignment"])
                .values(state="available")
            )
        inconsistent = await summary.view(env["order"], env["client"])
        assert inconsistent["states"] == {"unknown": 1, "unassigned": 1}
        assert "evidence" not in repr(inconsistent)
    finally:
        await flow["container"].dispose()


@pytest.mark.asyncio
async def test_summary_revoked_manager_cannot_read_old_order(
    capture_env, monkeypatch
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    try:
        with Session(env["pg"]) as db, db.begin():
            row = db.get(ManagerOrderModel, (flow["manager"], env["order"]))
            db.delete(row)
        with pytest.raises(LookupError, match="summary_not_found"):
            await service(env).view(env["order"], flow["manager"])
    finally:
        await flow["container"].dispose()


@pytest.mark.asyncio
async def test_actual_contact_receipt_is_not_work_success(delivery_env):
    env = delivery_env
    summary = service(env)
    before = await summary.view(env["order"], env["client"])
    assert before["contact_accepted"] == 0
    assert before["states"] == {"not_configured": 1, "unassigned": 1}
    await env["worker"].run_once()
    after = await summary.view(env["order"], env["client"])
    assert after["contact_accepted"] == 1
    assert after["states"] == before["states"]


@pytest.mark.asyncio
async def test_legacy_30_creator_summary_deduplicates_without_invented_success(
    capture_env, monkeypatch
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    order, creators = uuid4(), [uuid4() for _ in range(30)]
    at = datetime.now(timezone.utc)
    try:
        with Session(env["pg"]) as db, db.begin():
            db.add(
                OrderModel(
                    order_id=order,
                    advertiser_id=env["client"],
                    product_link="test",
                    offer_text="legacy summary",
                    price=1,
                    bloggers_needed=30,
                    status="closed",
                    created_at=at,
                )
            )
            db.add_all(
                [
                    UserModel(
                        user_id=c,
                        messenger_type="telegram",
                        username="synthetic",
                        status="active",
                    )
                    for c in creators
                ]
            )
            db.flush()
            db.add(
                ManagerOrderModel(
                    user_id=flow["manager"], order_id=order, created_at=at
                )
            )
            db.add_all(
                [
                    InteractionModel(
                        interaction_id=uuid4(),
                        order_id=order,
                        blogger_id=c,
                        advertiser_id=env["client"],
                        status="pending",
                        updated_at=at,
                    )
                    for c in creators
                ]
            )
            db.add(
                InteractionModel(
                    interaction_id=uuid4(),
                    order_id=order,
                    blogger_id=creators[0],
                    advertiser_id=env["client"],
                    status="ok",
                    updated_at=at + timedelta(seconds=1),
                )
            )
            db.add(
                InteractionModel(
                    interaction_id=uuid4(),
                    order_id=order,
                    blogger_id=flow["creator"],
                    advertiser_id=flow["partner"],
                    status="ok",
                    updated_at=at,
                )
            )
            db.add_all(
                [
                    OfferDispatchModel(
                        order_id=order,
                        blogger_id=c,
                        manager_id=flow["manager"],
                        in_offer=True,
                        accepted=True,
                    )
                    for c in creators[:2]
                ]
            )
        summary = service(env)
        own = await summary.view(order, env["client"])
        assert own["total"] == 30
        assert own["source"] == "legacy_feedback"
        assert own["states"] == {"legacy_ok": 1, "legacy_pending": 29}
        assert own["contact_accepted"] is None
        manager = await summary.view(order, flow["manager"])
        assert manager["total"] == 2
        assert manager["states"] == {"legacy_ok": 1, "legacy_pending": 1}
        assert str(creators[0]) not in repr(manager)
    finally:
        await flow["container"].dispose()


@pytest.mark.asyncio
async def test_summary_missing_order_and_inactive_actor_fail_explicitly(
    capture_env, monkeypatch
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    try:
        with pytest.raises(LookupError, match="summary_not_found"):
            await service(env).view(uuid4(), env["client"])
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["client"])
                .values(status="blocked")
            )
        with pytest.raises(PermissionError, match="summary_actor_inactive"):
            await service(env).view(env["order"], env["client"])
    finally:
        await flow["container"].dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("actor_role", ["client", "manager"])
async def test_signed_summary_real_factory_reads_own_scope_with_core_paused(
    capture_env, monkeypatch, platform, actor_role
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    actor = env["client"] if actor_role == "client" else flow["manager"]
    external = identity(env, actor)
    foreign = identity(env, flow["partner"])
    container = Container(configuration(env, enabled=False))
    path = f"/miniapp/api/orders/{env['order']}/campaign-summary"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app(container)),
            base_url="http://testserver",
        ) as client:
            response = await client.post(path, json=signed(external, platform))
            assert response.status_code == 200, response.text
            assert response.json()["role"] == actor_role
            assert response.json()["total"] == (
                2 if actor_role == "client" else 1
            )
            assert "provider_reference" not in response.text
            assert (
                await client.post(path, json=signed(foreign, platform))
            ).status_code == 404
            assert (
                await client.post(path, json={"init_data": "forged"})
            ).status_code == 401
            for extra in ({"actor_id": str(actor)}, {"success": True}):
                assert (
                    await client.post(
                        path, json={**signed(external, platform), **extra}
                    )
                ).status_code == 422
            assert (
                await client.post(
                    path + "?recipient_id=forged",
                    json=signed(external, platform),
                )
            ).status_code == 422
            if actor_role == "manager":
                with Session(env["pg"]) as db, db.begin():
                    db.execute(
                        delete(ManagerOrderModel).where(
                            ManagerOrderModel.user_id == actor,
                            ManagerOrderModel.order_id == env["order"],
                        )
                    )
                assert (
                    await client.post(path, json=signed(external, platform))
                ).status_code == 404
    finally:
        await container.dispose()
        await flow["container"].dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "relation",
    [
        "financial_collaboration_events",
        "financial_collaborations",
        "paid_selection_interests",
        "paid_selection_accepted_deliveries",
        "paid_selection_delivery_outcomes",
    ],
)
async def test_summary_missing_history_is_explicitly_unavailable(
    capture_env, monkeypatch, relation
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    try:
        with env["pg"].begin() as db:
            db.execute(
                text(f"ALTER TABLE {relation} RENAME TO summary_hidden_source")
            )
        try:
            with pytest.raises(ValueError, match="summary_history_unavailable"):
                await service(env).view(env["order"], env["client"])
        finally:
            with env["pg"].begin() as db:
                db.execute(
                    text(
                        "ALTER TABLE summary_hidden_source "
                        f"RENAME TO {relation}"
                    )
                )
    finally:
        await flow["container"].dispose()


@pytest.mark.asyncio
async def test_summary_does_not_mix_concurrent_work_versions(
    capture_env, monkeypatch
):
    from ugc_bot.infrastructure.db.repositories import (
        campaign_summary as module,
    )

    env = capture_env
    flow = await start_flow(env, monkeypatch)
    real_rows, changed = module._rows, False

    async def concurrent_write(db, statement):
        nonlocal changed
        result = await real_rows(db, statement)
        if not changed:
            changed = True
            await finish_work(env, flow)
        return result

    monkeypatch.setattr(module, "_rows", concurrent_write)
    try:
        old = await service(env).view(env["order"], env["client"])
        assert old["states"] == {"assigned": 1, "unassigned": 1}
        fresh = await service(env).view(env["order"], env["client"])
        assert fresh["states"] == {"success_final": 1, "unassigned": 1}
    finally:
        await flow["container"].dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "relation",
    [
        "financial_collaboration_events",
        "financial_collaborations",
        "paid_selection_interests",
        "paid_selection_accepted_deliveries",
        "paid_selection_delivery_outcomes",
    ],
)
async def test_signed_summary_capability_role_and_history_fail_honestly(
    capture_env, monkeypatch, relation
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    external = identity(env, env["client"])
    container = Container(configuration(env, enabled=False))
    application = app(container)
    path = f"/miniapp/api/orders/{env['order']}/campaign-summary"
    body = signed(external)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            actual = application.state.dispatcher["campaign_summary_service"]
            application.state.dispatcher["campaign_summary_service"] = None
            assert (await client.post(path, json=body)).status_code == 503
            application.state.dispatcher["campaign_summary_service"] = actual
            with Session(env["pg"]) as db, db.begin():
                db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == env["client"])
                    .values(status="blocked")
                )
            assert (await client.post(path, json=body)).status_code == 403
            with Session(env["pg"]) as db, db.begin():
                db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == env["client"])
                    .values(status="active")
                )
            with env["pg"].begin() as db:
                db.execute(
                    text(
                        f"ALTER TABLE {relation} "
                        "RENAME TO summary_hidden_source"
                    )
                )
            try:
                result = await client.post(path, json=body)
                assert result.status_code == 503
                assert relation not in result.text
                assert "unavailable" in result.text
            finally:
                with env["pg"].begin() as db:
                    db.execute(
                        text(
                            "ALTER TABLE summary_hidden_source "
                            f"RENAME TO {relation}"
                        )
                    )
    finally:
        await container.dispose()
        await flow["container"].dispose()
