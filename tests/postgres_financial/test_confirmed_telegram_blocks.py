"""The completed reminder ledger can be reconciled without contacting users."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from scripts import backfill_telegram_bot_blocks as backfill
from tests.postgres_financial.test_manager_creator_directory import (
    _creator,
    _profile,
)
from ugc_bot.admin.dashboard_service import (
    AdminDashboardService,
    DelayThresholds,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.models import UserModel, UserReferralBindingModel
from ugc_bot.infrastructure.db.repositories.bot_availability import (
    record_bot_availability,
)
from ugc_bot.infrastructure.db.repositories.manager_creator_directory import (
    invited_creator_page,
)


@pytest.mark.asyncio
async def test_reminder_refusals_appear_in_both_directories(
    financial_pg_engine, tmp_path, monkeypatch
):
    cases = [
        {"manager_slot": 1, "offset_seconds": 0, "has_max": True},
        {"manager_slot": 2, "offset_seconds": 1, "has_max": False},
        {"manager_slot": None, "offset_seconds": 2, "has_max": False},
    ]
    await exercise_refusal_import(
        financial_pg_engine, tmp_path, monkeypatch, cases
    )


async def exercise_refusal_import(engine, tmp_path, monkeypatch, cases):
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "telegram-test-token",
            "DATABASE_URL": engine.url.render_as_string(hide_password=False),
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
        }
    )
    monkeypatch.setattr(backfill, "load_config", lambda: config)
    container = Container(config)
    transactions = container.transaction_manager
    assert transactions
    factory = container.session_factory
    manager_slots = {row["manager_slot"] for row in cases} - {None}
    managers = {slot: uuid4() for slot in manager_slots}
    people = []
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    async with factory.begin() as db:
        for slot, user_id in managers.items():
            manager = _creator(user_id, UserStatus.ACTIVE)
            manager.telegram_id = str(100000 + slot)
            manager.max_id = str(200000 + slot)
            db.add(manager)
        for number, row in enumerate(cases, start=1):
            user = _creator(
                uuid4(),
                UserStatus(row.get("status", "active")),
                name=f"Import verification subject {number}",
            )
            user.telegram_id = str(300000 + number)
            if row["has_max"]:
                user.max_id = str(400000 + number)
                user.max_chat_id = str(500000 + number)
            people.append((user.user_id, user.telegram_id, row))
            db.add(user)
        extra = _creator(
            uuid4(), UserStatus.ACTIVE, name="Import verification extra"
        )
        extra.telegram_id = "600001"
        extra_id = extra.user_id
        db.add(extra)
        await db.flush()
        for user_id, _, row in people:
            db.add(_profile(user_id))
            if row["manager_slot"] is not None:
                db.add(
                    UserReferralBindingModel(
                        referrer_user_id=managers[row["manager_slot"]],
                        referred_user_id=user_id,
                    )
                )
        db.add(_profile(extra_id))
    members = [
        {
            "id": str(user_id),
            "route": route,
            "platform": "telegram",
            "state": "blocked_at_send",
            "attempted_at": (
                base + timedelta(seconds=row["offset_seconds"], microseconds=5)
            ).isoformat(),
        }
        for user_id, route, row in people
    ]
    members.append(
        {
            **members[0],
            "id": str(extra_id),
            "route": "600001",
            "state": "forbidden",
        }
    )
    ledger = tmp_path / "refusals.json"
    ledger.write_text(
        json.dumps(
            {
                "completed_at": (base + timedelta(hours=1)).isoformat(),
                "cohort": members,
            }
        ),
        encoding="utf-8",
    )
    filters = dict(
        period="all",
        only_new=False,
        only_with_complaints=False,
        per_page=100,
        q="Import verification",
    )
    dashboard = AdminDashboardService(
        factory,
        "Europe/Moscow",
        DelayThresholds(
            active_days=7,
            no_responses_hours=24,
            low_picked_hours=48,
            archive_days=7,
        ),
    )
    try:
        assert (await dashboard.list_creators(status="bot_blocked", **filters))[
            "total"
        ] == 0
        blocks = backfill.read_blocks(ledger)
        assert len(blocks) == len(people)
        assert await backfill.import_blocks(blocks) == len(people)
        assert await backfill.import_blocks(blocks) == 0
        assert (
            await backfill.import_blocks([(extra_id, people[0][1], base)]) == 0
        )
        unavailable = await dashboard.list_creators(
            status="bot_blocked", sort="status", **filters
        )
        assert unavailable["total"] == len(people)
        assert {item["user_id"] for item in unavailable["items"]} == {
            str(user_id) for user_id, _, _ in people
        }
        assert {item["status"] for item in unavailable["items"]} == {
            "bot_blocked"
        }
        first_user, route, _ = people[0]
        detail = await dashboard.get_user_card(first_user)
        assert detail["status_label"] == "bot_blocked"
        active = await dashboard.list_creators(status="active", **filters)
        assert {item["user_id"] for item in active["items"]} == {str(extra_id)}
        async with factory() as db:
            for slot, manager in managers.items():
                own_ids = {
                    user_id
                    for user_id, _, row in people
                    if row["manager_slot"] == slot
                }
                for platform, prefix in (("telegram", 100000), ("max", 200000)):
                    principal = AuthenticatedMessengerPrincipal(
                        manager, platform, str(prefix + slot)
                    )
                    results = await invited_creator_page(
                        db,
                        principal,
                        bot_unavailable=True,
                        offset=0,
                        limit=100,
                        q="Import verification",
                    )
                    assert {user.user_id for user, _, _ in results} == own_ids
                    assert {status for _, _, status in results} == {
                        UserStatus.BOT_BLOCKED
                    }
            assert await db.scalar(
                select(func.count())
                .select_from(UserModel)
                .where(
                    UserModel.user_id.in_(
                        [user_id for user_id, _, _ in people]
                    ),
                    UserModel.status == UserStatus.ACTIVE,
                )
            ) == len(people)
        # Backfilling old refusals cannot replace later proof of an unblock.
        assert await record_bot_availability(
            transactions,
            platform=MessengerType.TELEGRAM,
            external_id=route,
            available=True,
            occurred_at=base + timedelta(days=1),
            update_id=42,
        )
        assert await backfill.import_blocks(blocks) == 0
        restored = await dashboard.get_user_card(first_user)
        assert restored["status_label"] == "active"
        assert (await dashboard.list_creators(status="bot_blocked", **filters))[
            "total"
        ] == len(people) - 1
    finally:
        await container.dispose()
