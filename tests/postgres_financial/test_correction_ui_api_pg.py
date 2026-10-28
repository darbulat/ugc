"""Real mounted UI endpoints, current SQL sources, synthetic bank evidence."""

from dataclasses import asdict
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.conftest import (
    financial_pg_engine as _shared_engine,
)
from tests.postgres_financial.test_correction_commands_pg import (
    correction_env as correction_env,
)
from tests.postgres_financial.test_correction_commands_pg import (
    intake_env as intake_env,
)
from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.config import MaxBotConfig
from ugc_bot.container.correction_factory import build_correction_services
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import OrderModel, UserModel

__all__ = ["correction_env", "intake_env"]


@pytest.fixture
def financial_pg_engine(request):
    # The bounded global admin queue belongs to this scenario's real facts.
    # Reuse the current-head migrator with a fresh UUID schema for each test.
    yield from _shared_engine.__wrapped__(request)


def application(rt, platform):
    from ugc_bot.miniapp.api import router

    env = rt.env
    config = env["config"]
    config.max_bot = MaxBotConfig.model_validate(
        {"MAX_BOT_TOKEN": "synthetic-max-token"}
    )
    config.financial.manual_bank_source_id = "synthetic-correction-bank"
    config.financial.manual_bank_account_id = "synthetic-correction-account"
    commands, views = build_correction_services(
        config,
        env["container"].transaction_manager,
        env["container"].session_factory,
    )
    # Test clock is declared synthetic; no bank/provider or production flag.
    commands.clock = views.clock = commands.physical_proofs.clock = env["clock"]
    app = FastAPI()
    app.state.config = config
    app.state.dispatcher = env["container"].build_bot_services() | dict(
        correction_service=commands,
        correction_view_service=views,
        transaction_manager=env["container"].transaction_manager,
    )
    app.include_router(router, prefix="/miniapp")

    def auth(actor):
        native = rt.principal(actor, platform).external_id
        return dict(
            platform=platform,
            init_data=generate_init_data(
                config.bot.bot_token
                if platform == "telegram"
                else config.max_bot.token,
                native,
                "Synthetic",
            ),
        )

    return app, auth(env["user"].user_id), auth(env["admin"].user_id)


async def post(client, auth, path, **values):
    return await client.post(
        "/miniapp/api/financial/corrections/" + path, json=auth | values
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_mounted_sql_refund_ui_retains_exact_evidence_without_application(
    correction_env, platform
):
    rt = correction_env
    app, own, admin = application(rt, platform)
    command = await rt.request()
    before = {
        kind: len(rt.rows(kind))
        for kind in ("cases", "commands", "observations", "matches")
    }
    values = canonical(
        dict(
            order_id=command.order_id,
            paid_item_ids=command.paid_item_ids,
            expected_source_hash=command.expected_source_hash,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        orders = await post(client, own, "orders")
        assert orders.status_code == 200, orders.text
        assert len(orders.json()["entries"][0]["items"]) == 30
        preview = await post(
            client,
            own,
            "preview",
            **{k: values[k] for k in ("order_id", "paid_item_ids")},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["total_minor"] == "250000"
        assert preview.json()["source_hash"] == command.expected_source_hash
        assert preview.json()["can_request"] is False
        assert len(rt.rows("cases")) == before["cases"]
        assert len(rt.rows("commands")) == before["commands"]
        state = await rt.execute(command)
        requested = await post(
            client,
            own,
            "request",
            **values,
            operation_key="ui-sql-request",
            reason="Five expired undelivered positions",
        )
        assert requested.status_code == 404
        approved = await post(
            client,
            admin,
            "admin/review",
            operation_key="ui-sql-review",
            reason="PRIVATE REVIEW",
            case_id=state["case_id"],
            expected_version=state["version"],
            expected_source_hash=state["source_hash"],
            decision="approve",
            evidence_reference="PRIVATE REVIEW REFERENCE",
            evidence_hash="b" * 64,
        )
        assert approved.status_code == 200, approved.text
        report = rt.observation(approved.json())
        report_values = canonical(asdict(report))
        for key in ("actor_id", "provenance"):
            report_values.pop(key)
        report_values["amount_minor"] = "250000"
        observed = await post(
            client, admin, "admin/observation", **report_values
        )
        assert observed.status_code == 200, observed.text
        matched = await post(
            client,
            admin,
            "admin/match",
            operation_key="ui-sql-match",
            reason="PRIVATE MATCH",
            case_id=state["case_id"],
            intent_id=approved.json()["intent_id"],
            observation_id=observed.json()["observation_id"],
            expected_version=observed.json()["version"],
            expected_source_hash=observed.json()["source_hash"],
            evidence_reference="PRIVATE MATCH REFERENCE",
            evidence_hash="c" * 64,
        )
        assert matched.status_code == 200, matched.text
        assert matched.json()["applied"] is False
        assert matched.json()["application_status"] == "awaiting_assessment"
        assert not rt.rows(
            "applications", intent_id=UUID(approved.json()["intent_id"])
        )
        assert len(rt.rows("observations")) == before["observations"] + 1
        assert len(rt.rows("matches")) == before["matches"] + 1
        own_detail = await post(client, own, state["case_id"] + "/detail")
        assert own_detail.status_code == 200, own_detail.text
        assert own_detail.json()["paid_item_ids"] == values["paid_item_ids"]
        assert own_detail.json()["total_minor"] == "250000"
        assert "PRIVATE" not in own_detail.text
        assert "synthetic:refund" not in own_detail.text
        assert "observations" not in own_detail.json()
        admin_detail = await post(client, admin, state["case_id"] + "/detail")
        assert admin_detail.status_code == 200, admin_detail.text
        assert (
            admin_detail.json()["observations"][0]["amount_minor"] == "250000"
        )
        assert "PRIVATE REVIEW REFERENCE" in admin_detail.text
        own_list = await post(client, own, "list")
        assert own_list.json()["entries"][0]["case_id"] == state["case_id"]
        assert "PRIVATE" not in own_list.text
        original = await post(
            client, own, "operations/status", operation_key="ui-sql-request"
        )
        assert original.json()["original_result"] == state
        assert original.json()["current"]["version"] == 4
        assert original.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_sql_lists_apply_current_ownership_and_keep_orphans_admin_only(
    correction_env,
):
    rt = correction_env
    requested = await rt.execute(await rt.request())
    app, own, admin = application(rt, "telegram")
    orphan = await rt.execute(
        rt.observation(known_order_id=None, known_capture_intent_id=None)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        own_list = await post(client, own, "list", limit=1)
        assert own_list.status_code == 200, own_list.text
        assert [r["case_id"] for r in own_list.json()["entries"]] == [
            requested["case_id"]
        ]
        first = await post(client, admin, "admin/queue", limit=1)
        assert first.json()["has_more"] is True
        second = await post(
            client,
            admin,
            "admin/queue",
            limit=1,
            cursor=first.json()["next_cursor"],
        )
        assert second.json()["has_more"] is False
        assert second.json()["next_cursor"] is None
        ids = [
            first.json()["entries"][0]["case_id"],
            second.json()["entries"][0]["case_id"],
        ]
        assert set(ids) == {requested["case_id"], orphan["case_id"]}
        attached = await rt.execute(
            await rt.request(existing_case_id=UUID(orphan["case_id"]))
        )
        own_attached = await post(client, own, "list")
        assert {row["case_id"] for row in own_attached.json()["entries"]} == {
            requested["case_id"],
            attached["case_id"],
        }
        attached_row = next(
            row
            for row in own_attached.json()["entries"]
            if row["case_id"] == attached["case_id"]
        )
        assert attached_row["order_id"] == str(rt.facts["order"].order_id)
        with Session(rt.env["pg"]) as db, db.begin():
            db.execute(
                update(OrderModel)
                .where(OrderModel.order_id == rt.facts["order"].order_id)
                .values(advertiser_id=rt.facts["stranger"])
            )
        after = await post(client, own, "list")
        assert after.status_code == 200 and after.json()["entries"] == []
        refused = await post(client, own, requested["case_id"] + "/detail")
        assert refused.status_code == 403
        assert (await post(client, own, "orders")).json()["entries"] == []
        with Session(rt.env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == rt.env["admin"].user_id)
                .values(admin=False)
            )
        denied = await post(client, admin, "admin/queue")
        assert denied.status_code == 403
        assert orphan["case_id"] not in denied.text


@pytest.mark.asyncio
async def test_sql_order_navigation_is_bounded_and_rejects_oversized_source(
    correction_env,
):
    rt = correction_env
    app, own, _ = application(rt, "telegram")
    from tests.postgres_financial.test_order_intake import command, service

    unpaid = await service(rt.env).create(command(rt.env))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        orders = await post(client, own, "orders", limit=1)
        assert [r["order_id"] for r in orders.json()["entries"]] == [
            str(rt.facts["order"].order_id)
        ]
        assert str(unpaid.order_id) not in orders.text
        after = await post(
            client, own, "orders", cursor=str(rt.facts["order"].order_id)
        )
        assert after.json()["entries"] == []
        # Explicit new-row source fault; no captured/immutable fact is changed.
        items = Base.metadata.tables["order_items"]
        with Session(rt.env["pg"]) as db, db.begin():
            original = dict(
                db.execute(
                    select(items)
                    .where(items.c.order_id == rt.facts["order"].order_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
            original.update(paid_item_id=uuid4(), ordinal=31)
            db.execute(insert(items).values(**original))
        invalid = await post(client, own, "orders")
        assert invalid.status_code == 409
        assert invalid.json() == {"detail": "correction_source_unavailable"}


@pytest.mark.asyncio
async def test_early_owned_case_offers_real_positions_without_invented_subset(
    correction_env,
):
    rt = correction_env
    early = await rt.execute(rt.observation())
    app, own, admin = application(rt, "telegram")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        detail = await post(client, own, early["case_id"] + "/detail")
        assert detail.status_code == 200, detail.text
        value = detail.json()
        assert value["paid_item_ids"] == [] and value["request"] is None
        assert {row["paid_item_id"] for row in value["available_items"]} == {
            str(item.paid_item_id) for item in rt.facts["order"].items
        }
        assert len(value["available_items"]) == 30
        assert "request" not in value["allowed_actions"]
        private = await post(client, admin, early["case_id"] + "/detail")
        assert private.json()["available_items"] == []
        chosen = [
            str(item.paid_item_id) for item in rt.facts["order"].items[-5:]
        ]
        preview = await post(
            client,
            own,
            "preview",
            order_id=str(rt.facts["order"].order_id),
            paid_item_ids=chosen,
            existing_case_id=early["case_id"],
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["total_minor"] == "250000"
        assert preview.json()["can_request"] is False
        assert not rt.rows("requests", case_id=UUID(early["case_id"]))
