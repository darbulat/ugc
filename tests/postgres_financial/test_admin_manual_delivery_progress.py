"""Manual receipts affect admin display without changing financial records."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.postgres_financial.test_creator_social import seed_profile
from tests.postgres_financial.test_telegram_order_summary import (
    financial_pg_engine,
    intake_env,
    paid_order,
)
from ugc_bot.admin.dashboard_service import (
    AdminDashboardService,
    DelayThresholds,
)
from ugc_bot.admin.order_progress import OrderProgress, load_order_progress
from ugc_bot.admin.order_worklist import worklist_row_details
from ugc_bot.infrastructure.db.invite_handoff_models import NOTICES
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    FinancialMovementModel,
    ItemAssignmentModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.creator_invites import create_invite
from ugc_bot.infrastructure.db.repositories.creator_transfers import (
    delivered_count,
)

__all__ = ["financial_pg_engine", "intake_env"]


@pytest.mark.asyncio
@pytest.mark.parametrize("registered", [False, True])
async def test_existing_manual_receipt_is_third_contact_across_admin_views(
    intake_env,
    registered,
):
    env = intake_env
    _, order_id, _, _, _ = await paid_order(env, interested_creators=2)
    thresholds = DelayThresholds(7, 24, 48, 30)
    with Session(env["pg"]) as db, db.begin():
        assert load_order_progress(db, [order_id])[order_id] == OrderProgress(
            2, 2
        )
        baseline = db.scalar(
            select(func.count()).select_from(FinancialMovementModel)
        )
        db.get(OrderModel, order_id).created_at = datetime.now(
            timezone.utc
        ) - timedelta(days=8)
        if registered:
            creator = seed_profile(db, stable_id=uuid4().hex)
            user = db.get(UserModel, creator)
            user.telegram = "manual_creator"
            user.status = "bot_blocked"
            profile = db.get(BloggerProfileModel, creator)
            profile.instagram_url = "https://instagram.com/manual_creator"
            db.flush()
        item = db.scalar(
            select(OrderItemModel.paid_item_id).where(
                OrderItemModel.order_id == order_id,
                OrderItemModel.ordinal == 3,
            )
        )
        identity = create_invite(
            db,
            order_id,
            item,
            None,
            "@manual_creator",
            env["clock"].now(),
            telegram="@manual_creator",
            consent_source="other",
            creator_name="Мурат",
        )
        # Existing persisted provider-accepted receipt; rendering sends nothing.
        db.execute(
            NOTICES.insert().values(
                invite_id=identity, kind="customer", state="sent"
            )
        )
        assert load_order_progress(db, [order_id])[order_id] == OrderProgress(
            2, 3, 1
        )
        details = worklist_row_details(db, [order_id], thresholds)[order_id]
        assert details["transferred_count"] == 3
        assert details["manual_transferred_count"] == 1
        assert details["picked"] == 2
    dashboard = AdminDashboardService(
        env["container"].session_factory,
        "Europe/Moscow",
        thresholds,
    )
    orders = await dashboard.list_orders("all", search=str(order_id))
    row = next(
        row for row in orders["items"] if row["order_id"] == str(order_id)
    )
    assert (
        row["transferred_count"] == 3 and row["manual_transferred_count"] == 1
    )
    async with env["container"].session_factory() as db:
        attention = await dashboard._get_order_attention(db)
        row = next(
            row
            for row in attention["delayed"]
            if row["order_id"] == str(order_id)
        )
        assert (
            row["transferred_count"] == 3
            and row["manual_transferred_count"] == 1
        )
        # Financial/customer acknowledgement history keeps its original meaning.
        assert await delivered_count(db, order_id) == 2
    activity = await dashboard.get_order_workspace_activity(
        order_id, can_send=True
    )
    workspace = activity["workspace"]
    assert workspace["transfer_count"] == 3 and workspace["manual_count"] == 1
    (manual,) = [row for row in workspace["rows"] if row["manual"]]
    assert manual["name"] == "Мурат" and manual["ordinal"] == 3
    assert manual["delivered"] and not manual["can_send"]
    assert bool(manual["profile_id"]) == registered
    assert len(workspace["rows"]) == 3
    with Session(env["pg"]) as db:
        assert (
            db.scalar(select(func.count()).select_from(FinancialMovementModel))
            == baseline
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ItemAssignmentModel)
                .join(OrderItemModel)
                .where(
                    OrderItemModel.order_id == order_id,
                )
            )
            == 2
        )
