"""Business concurrency proofs against independent PostgreSQL connections."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.manager_service import ManagerService
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    ComplaintModel,
    InteractionModel,
    ManagerOrderModel,
    OfferDispatchModel,
    OrderModel,
    ReferralIncomeEntryModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.interactions import (
    SqlAlchemyInteractionRepository,
    SqlAlchemyOfferDispatchRepository,
)
from ugc_bot.infrastructure.db.repositories.orders import (
    SqlAlchemyOrderRepository,
)
from ugc_bot.infrastructure.db.repositories.support import (
    SqlAlchemyComplaintRepository,
    SqlAlchemyManagerOrderRepository,
)
from ugc_bot.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from ugc_bot.infrastructure.db.session import SessionTransactionManager
from ugc_bot.miniapp import api


@pytest_asyncio.fixture
async def manager_pg(financial_pg_engine):
    engine = create_async_engine(financial_pg_engine.url, pool_size=5)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    manager, replacement, advertiser, blogger, second, order = [
        uuid4() for _ in range(6)
    ]
    async with factory.begin() as s:
        s.add_all(
            [
                UserModel(
                    user_id=x,
                    messenger_type=MessengerType.TELEGRAM,
                    username="synthetic",
                    status=UserStatus.ACTIVE,
                    issue_count=0,
                    created_at=now,
                )
                for x in (manager, replacement, advertiser, blogger, second)
            ]
        )
        await s.flush()
        s.add(
            OrderModel(
                order_id=order,
                advertiser_id=advertiser,
                order_type=OrderType.UGC_ONLY,
                product_link="https://example.com",
                offer_text="synthetic",
                price=100,
                bloggers_needed=1,
                status=OrderStatus.ACTIVE,
                created_at=now,
            )
        )
        await s.flush()
        s.add_all(
            [
                ManagerOrderModel(
                    order_id=order, user_id=x, created_at=now, updated_at=now
                )
                for x in (manager, replacement)
            ]
        )
        s.add_all(
            [
                OfferDispatchModel(
                    order_id=order,
                    blogger_id=x,
                    manager_id=manager,
                    accepted=True,
                    in_offer=False,
                    created_at=now,
                )
                for x in (blogger, second)
            ]
        )
    repo = SqlAlchemyOfferDispatchRepository(factory)
    service = ManagerService(
        SqlAlchemyManagerOrderRepository(factory),
        SqlAlchemyUserRepository(factory),
        SqlAlchemyOrderRepository(factory),
        repo,
        SessionTransactionManager(factory),
    )
    yield (
        factory,
        service,
        (manager, replacement, advertiser, blogger, second, order),
    )
    await engine.dispose()


@pytest.mark.asyncio
async def test_return_revalidates_reassignment_committed_while_read_waits(
    manager_pg,
):
    factory, service, (manager, replacement, _, blogger, _, order) = manager_pg
    started = asyncio.Event()
    connections = set()
    async with factory.begin() as owner:
        owner_pid = await owner.scalar(text("select pg_backend_pid()"))
        connections.add(owner_pid)
        await service.offer_dispatch_repo.set_manager(
            order, blogger, replacement, session=owner
        )

        async def returning():
            started.set()
            return await service.assign_returning_creator(
                order, blogger, manager
            )

        task = asyncio.create_task(returning())
        await started.wait()
        # Observe actual lock contention, not an arbitrary sleep.
        async with factory() as observer:
            for _ in range(200):
                # pg_stat_activity caches a transaction-local snapshot; a new
                # contender PID must become visible after the first sample.
                await observer.execute(text("select pg_stat_clear_snapshot()"))
                waiting = await observer.scalar(
                    text(
                        "select pid from pg_stat_activity "
                        "where :owner=ANY(pg_blocking_pids(pid))"
                    ),
                    {"owner": owner_pid},
                )
                if waiting:
                    break
                await asyncio.sleep(0.01)
            assert waiting, "the return must reach the competing transaction"
            connections.add(waiting)
            assert waiting != owner_pid
    with pytest.raises(PermissionError):
        await task
    assert len(connections) == 2
    async with factory() as s:
        row = await s.scalar(
            select(OfferDispatchModel).where(
                OfferDispatchModel.order_id == order,
                OfferDispatchModel.blogger_id == blogger,
            )
        )
        assert row.manager_id == replacement
        assert not row.in_offer, (
            "the old manager must not restore a reassigned creator"
        )


@pytest.mark.asyncio
async def test_two_returns_cannot_consume_the_same_last_slot(manager_pg):
    _, service, (manager, _, _, blogger, second, order) = manager_pg
    results = await asyncio.gather(
        service.assign_returning_creator(order, blogger, manager),
        service.assign_returning_creator(order, second, manager),
        return_exceptions=True,
    )
    assert sum(not isinstance(x, BaseException) for x in results) == 1
    assert sum(isinstance(x, ValueError) for x in results) == 1
    assert await service.offer_dispatch_repo.count_accepted_by_order(order) == 1


def _api_dependencies(factory, service):
    referral = MagicMock(record_creator_referral_income=AsyncMock())
    interactions = InteractionService(
        SqlAlchemyInteractionRepository(factory),
        transaction_manager=service.transaction_manager,
        referral_income_service=referral,
        order_repo=service.order_repo,
        user_repo=service.user_repo,
    )
    deps = {
        "manager_service": service,
        "order_repo": service.order_repo,
        "offer_dispatch_repo": service.offer_dispatch_repo,
        "user_repo": service.user_repo,
        "interaction_service": interactions,
        "complaint_service": ComplaintService(
            SqlAlchemyComplaintRepository(factory),
            transaction_manager=service.transaction_manager,
        ),
        "messenger_client": MagicMock(send_text=AsyncMock()),
        "bot_texts_service": MagicMock(
            get=AsyncMock(return_value="{manager_telegram}")
        ),
        "user_role_service": MagicMock(),
    }
    request = MagicMock()
    request.app.state.dispatcher = deps
    return request, deps, referral


def _operation(operation):
    return {
        "video": (
            api.manager_set_ugc_video,
            api.UgcVideoRequest(
                init_data="synthetic", url="https://example.com/video"
            ),
        ),
        "remove": (
            api.manager_remove_creator,
            api.InitDataBody(init_data="synthetic"),
        ),
        "add": (
            api.manager_add_creator,
            api.InitDataBody(init_data="synthetic"),
        ),
        "feedback": (
            api.manager_feedback,
            api.ManagerFeedbackRequest(init_data="synthetic", status="ok"),
        ),
        "issue": (
            api.manager_feedback,
            api.ManagerFeedbackRequest(
                init_data="synthetic",
                status="issue",
                issue_description="synthetic complaint",
            ),
        ),
    }[operation]


async def _wait_for_contender(factory, owner_pid, task=None):
    async with factory() as observer:
        for _ in range(300):
            if task is not None and task.done():
                return None
            await observer.execute(text("select pg_stat_clear_snapshot()"))
            contender = await observer.scalar(
                text(
                    "select pid from pg_stat_activity "
                    "where :owner=ANY(pg_blocking_pids(pid))"
                ),
                {"owner": owner_pid},
            )
            if contender:
                assert contender != owner_pid
                return contender
            await asyncio.sleep(0.01)
    pytest.fail(
        "command never reached the row lock held by the independent session"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["video", "remove", "add", "feedback", "issue"]
)
async def test_api_reassignment_between_authorization_and_write_is_denied(
    manager_pg, operation
):
    factory, service, (manager, replacement, _, blogger, _, order) = manager_pg
    if operation != "add":
        await service.offer_dispatch_repo.set_in_offer(order, blogger, True)
    request, deps, referral = _api_dependencies(factory, service)
    endpoint, body = _operation(operation)
    authorized = asyncio.Event()
    original = api._authorize_manager_creator
    async with factory.begin() as owner:
        owner_pid = await owner.scalar(text("select pg_backend_pid()"))

        async def reassign(*args, **kwargs):
            await original(*args, **kwargs)
            await service.offer_dispatch_repo.set_manager(
                order, blogger, replacement, session=owner
            )
            authorized.set()

        with (
            patch.object(
                api, "_ensure_user_and_get_id", AsyncMock(return_value=manager)
            ),
            patch.object(api, "_authorize_manager_creator", reassign),
        ):
            task = asyncio.create_task(endpoint(request, order, blogger, body))
            await asyncio.wait_for(authorized.wait(), timeout=5)
            contender = await _wait_for_contender(factory, owner_pid, task)
            # No command-side effect is possible while authorization is stale.
            referral.record_creator_referral_income.assert_not_awaited()
            deps["messenger_client"].send_text.assert_not_awaited()
    with pytest.raises(HTTPException) as exc:
        await task
    assert exc.value.status_code == 403
    assert contender is not None, "SQL authorization must hold a real row lock"
    async with factory() as s:
        row = await s.scalar(
            select(OfferDispatchModel).where(
                OfferDispatchModel.order_id == order,
                OfferDispatchModel.blogger_id == blogger,
            )
        )
        assert row.manager_id == replacement
        assert row.in_offer is (operation != "add")
        assert row.ugc_video_url is None
        assert (
            await s.scalar(
                select(func.count())
                .select_from(InteractionModel)
                .where(InteractionModel.order_id == order)
            )
            == 0
        )
        assert (
            await s.scalar(
                select(func.count())
                .select_from(ComplaintModel)
                .where(ComplaintModel.order_id == order)
            )
            == 0
        )
        assert (
            await s.scalar(
                select(func.count())
                .select_from(ReferralIncomeEntryModel)
                .where(ReferralIncomeEntryModel.order_id == order)
            )
            == 0
        )
    referral.record_creator_referral_income.assert_not_awaited()
    deps["messenger_client"].send_text.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["video", "remove", "add", "feedback", "issue"]
)
async def test_authorized_api_command_writes_and_effects_are_after_one_commit(
    manager_pg, operation
):
    factory, service, (manager, _, _, blogger, _, order) = manager_pg
    if operation != "add":
        await service.offer_dispatch_repo.set_in_offer(order, blogger, True)
    request, deps, _ = _api_dependencies(factory, service)
    endpoint, body = _operation(operation)
    # Synthetic chat; every transport below is intercepted.
    from sqlalchemy import update

    async with factory.begin() as s:
        await s.execute(
            update(UserModel)
            .where(UserModel.user_id == blogger)
            .values(telegram_id=blogger.int % 10**12)
        )
    effects = []

    async def after_commit(*args, **kwargs):
        async with factory() as observer:
            rows = (
                await observer.scalars(
                    select(InteractionModel).where(
                        InteractionModel.order_id == order
                    )
                )
            ).all()
            assert len(rows) == 1, (
                "notification observed an uncommitted/missing interaction"
            )
            row = await observer.scalar(
                select(OfferDispatchModel).where(
                    OfferDispatchModel.order_id == order,
                    OfferDispatchModel.blogger_id == blogger,
                )
            )
            assert row.in_offer is (operation != "remove")
            if operation == "video":
                assert row.ugc_video_url == "https://example.com/video"
            if operation == "issue":
                assert (
                    await observer.scalar(
                        select(func.count())
                        .select_from(ComplaintModel)
                        .where(ComplaintModel.order_id == order)
                    )
                    == 1
                )
        effects.append("after_commit")

    with (
        patch.object(
            api, "_ensure_user_and_get_id", AsyncMock(return_value=manager)
        ),
        patch.object(
            api, "send_with_retry", AsyncMock(side_effect=after_commit)
        ),
        patch.object(
            api, "_notify_ugc_video_saved", AsyncMock(side_effect=after_commit)
        ),
        patch.object(
            api,
            "notify_admins_about_complaint",
            AsyncMock(side_effect=after_commit),
        ),
    ):
        result = await endpoint(request, order, blogger, body)
    assert result["ok"] is True
    async with factory() as observer:
        rows = (
            await observer.scalars(
                select(InteractionModel).where(
                    InteractionModel.order_id == order
                )
            )
        ).all()
        assert len(rows) == 1
        if operation in ("remove", "feedback", "issue"):
            assert rows[0].from_advertiser is not None
        if operation == "issue":
            assert rows[0].status.value == "issue"
    if operation != "feedback":
        assert effects == ["after_commit"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["video", "remove", "add", "feedback", "issue"]
)
async def test_commit_failure_rolls_back_all_command_writes_and_sends_nothing(
    manager_pg, operation
):
    from contextlib import asynccontextmanager

    factory, service, (manager, _, _, blogger, _, order) = manager_pg
    if operation != "add":
        await service.offer_dispatch_repo.set_in_offer(order, blogger, True)
    request, deps, referral = _api_dependencies(factory, service)

    @asynccontextmanager
    async def failed_commit():
        async with factory() as s:
            try:
                yield s
                await s.flush()
                raise RuntimeError("synthetic commit failure")
            finally:
                await s.rollback()

    # Only the command fails; preliminary reads use real transactions.
    real_authorize = api._authorize_manager_creator

    async def fail_after_authorize(*args, **kwargs):
        await real_authorize(*args, **kwargs)
        service.transaction_manager = MagicMock(transaction=failed_commit)

    endpoint, body = _operation(operation)
    with (
        patch.object(
            api, "_ensure_user_and_get_id", AsyncMock(return_value=manager)
        ),
        patch.object(api, "_authorize_manager_creator", fail_after_authorize),
        patch.object(api, "send_with_retry", AsyncMock()) as send,
        patch.object(api, "_notify_ugc_video_saved", AsyncMock()) as video,
        patch.object(
            api, "notify_admins_about_complaint", AsyncMock()
        ) as complaint,
        pytest.raises(RuntimeError, match="synthetic commit failure"),
    ):
        await endpoint(request, order, blogger, body)
    async with factory() as s:
        row = await s.scalar(
            select(OfferDispatchModel).where(
                OfferDispatchModel.order_id == order,
                OfferDispatchModel.blogger_id == blogger,
            )
        )
        assert row.in_offer is (operation != "add")
        assert row.ugc_video_url is None
        assert (
            await s.scalar(
                select(func.count())
                .select_from(InteractionModel)
                .where(InteractionModel.order_id == order)
            )
            == 0
        )
        assert (
            await s.scalar(
                select(func.count())
                .select_from(ComplaintModel)
                .where(ComplaintModel.order_id == order)
            )
            == 0
        )
    send.assert_not_awaited()
    video.assert_not_awaited()
    complaint.assert_not_awaited()
    referral.record_creator_referral_income.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["video", "remove", "add", "feedback"])
async def test_admin_pair_override_is_explicit_and_audited_after_commit(
    manager_pg, operation, caplog
):
    from sqlalchemy import update

    factory, service, (admin, replacement, _, blogger, _, order) = manager_pg
    async with factory.begin() as s:
        await s.execute(
            update(UserModel)
            .where(UserModel.user_id == admin)
            .values(admin=True)
        )
        await s.execute(
            update(OfferDispatchModel)
            .where(
                OfferDispatchModel.order_id == order,
                OfferDispatchModel.blogger_id == blogger,
            )
            .values(manager_id=replacement, in_offer=operation != "add")
        )
    request, _, _ = _api_dependencies(factory, service)
    endpoint, body = _operation(operation)
    with (
        caplog.at_level("INFO"),
        patch.object(
            api, "_ensure_user_and_get_id", AsyncMock(return_value=admin)
        ),
        patch.object(api, "_notify_ugc_video_saved", AsyncMock()),
    ):
        result = await endpoint(request, order, blogger, body)
    assert result["ok"] is True
    audit = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "admin_manager_pair_mutation"
    ]
    assert len(audit) == 1
    assert audit[0].user_id == str(admin)
    assert audit[0].order_id == str(order)
    assert audit[0].blogger_id == str(blogger)
    assert audit[0].previous_manager_id == str(replacement)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["video", "remove", "add", "feedback"])
async def test_pair_lock_is_held_from_revalidation_through_write_commit(
    manager_pg, operation
):
    factory, service, (manager, replacement, _, blogger, _, order) = manager_pg
    if operation != "add":
        await service.offer_dispatch_repo.set_in_offer(order, blogger, True)
    request, _, _ = _api_dependencies(factory, service)
    reached, resume = asyncio.Event(), asyncio.Event()
    pids = {}
    if operation == "video":
        cls, method = SqlAlchemyOfferDispatchRepository, "set_ugc_video_url"
    elif operation in ("remove", "add"):
        cls, method = SqlAlchemyOfferDispatchRepository, "set_in_offer"
    else:
        cls, method = SqlAlchemyInteractionRepository, "save"
    original = getattr(cls, method)

    async def pause_write(self, *args, **kwargs):
        session = kwargs.get("session")
        assert session is not None, "write escaped the authorizing SQL session"
        pids["command"] = await session.scalar(text("select pg_backend_pid()"))
        reached.set()
        await resume.wait()
        return await original(self, *args, **kwargs)

    endpoint, body = _operation(operation)

    async def reassign():
        async with factory.begin() as s:
            pids["reassignment"] = await s.scalar(
                text("select pg_backend_pid()")
            )
            await service.offer_dispatch_repo.set_manager(
                order, blogger, replacement, session=s
            )

    with (
        patch.object(
            api, "_ensure_user_and_get_id", AsyncMock(return_value=manager)
        ),
        patch.object(cls, method, pause_write),
        patch.object(api, "_notify_ugc_video_saved", AsyncMock()),
    ):
        command = asyncio.create_task(endpoint(request, order, blogger, body))
        await asyncio.wait_for(reached.wait(), timeout=5)
        competing = asyncio.create_task(reassign())
        try:
            blocked = await _wait_for_contender(
                factory, pids["command"], competing
            )
            assert blocked is not None, (
                "reassignment overtook an authorized write"
            )
            assert blocked == pids["reassignment"] != pids["command"]
        finally:
            resume.set()
        assert (await command)["ok"] is True
        await competing
    async with factory() as s:
        row = await s.scalar(
            select(OfferDispatchModel).where(
                OfferDispatchModel.order_id == order,
                OfferDispatchModel.blogger_id == blogger,
            )
        )
        assert row.manager_id == replacement
        assert row.in_offer is (operation != "remove")
        if operation == "video":
            assert row.ugc_video_url == "https://example.com/video"
        interaction = await s.scalar(
            select(InteractionModel).where(InteractionModel.order_id == order)
        )
        assert interaction is not None
        if operation in ("remove", "feedback"):
            assert interaction.from_advertiser is not None


@pytest.mark.asyncio
async def test_success_referral_is_called_only_after_committed_feedback(
    manager_pg,
):
    from sqlalchemy import update

    factory, service, (manager, _, advertiser, blogger, _, order) = manager_pg
    await service.offer_dispatch_repo.set_in_offer(order, blogger, True)
    request, deps, referral = _api_dependencies(factory, service)
    interaction_service = deps["interaction_service"]
    interaction = await interaction_service.get_or_create(
        order, blogger, advertiser
    )
    await interaction_service.record_blogger_feedback(
        interaction.interaction_id, "✅ Сделка состоялась"
    )
    async with factory.begin() as s:
        await s.execute(
            update(OrderModel)
            .where(OrderModel.order_id == order)
            .values(status=OrderStatus.CLOSED)
        )
        await s.execute(
            update(UserModel)
            .where(UserModel.user_id == advertiser)
            .values(country="ru")
        )
    committed = []

    async def referral_after_commit(**kwargs):
        async with factory() as observer:
            saved = await observer.get(
                InteractionModel, interaction.interaction_id
            )
            assert saved.status.value == "ok"
            assert saved.from_advertiser == "✅ Всё прошло хорошо"
            committed.append(True)

    referral.record_creator_referral_income.side_effect = referral_after_commit
    with patch.object(
        api, "_ensure_user_and_get_id", AsyncMock(return_value=manager)
    ):
        result = await api.manager_feedback(
            request,
            order,
            blogger,
            api.ManagerFeedbackRequest(init_data="synthetic", status="ok"),
        )
    assert result["ok"]
    referral.record_creator_referral_income.assert_awaited_once()
    assert committed == [True], "referral ran before feedback became visible"


@pytest.mark.asyncio
async def test_manager_no_deal_reason_cannot_forge_success_or_erase_case(
    manager_pg,
):
    from ugc_bot.domain.enums import InteractionStatus
    from ugc_bot.infrastructure.db.models import LegacyFinancialCaseModel

    factory, service, (manager, _, advertiser, blogger, _, order) = manager_pg
    await service.offer_dispatch_repo.set_in_offer(order, blogger, True)
    request, deps, referral = _api_dependencies(factory, service)
    interaction = await deps["interaction_service"].get_or_create(
        order, blogger, advertiser
    )
    await deps["interaction_service"].record_blogger_feedback(
        interaction.interaction_id, "✅ Всё хорошо"
    )
    with patch.object(
        api, "_ensure_user_and_get_id", AsyncMock(return_value=manager)
    ):
        await api.manager_feedback(
            request,
            order,
            blogger,
            api.ManagerFeedbackRequest(
                init_data="synthetic",
                status="no_deal",
                no_deal_reason="клиент написал ✅; ещё не связался ⏳",
            ),
        )
    async with factory() as db:
        row = await db.get(InteractionModel, interaction.interaction_id)
        case = await db.get(
            LegacyFinancialCaseModel, interaction.interaction_id
        )
        assert row.status == InteractionStatus.ISSUE
        assert case is not None and case.released is False
    referral.record_creator_referral_income.assert_not_awaited()


@pytest.mark.asyncio
async def test_manager_can_report_two_creators_and_retry_same_issue(manager_pg):
    from sqlalchemy import update

    from ugc_bot.domain.enums import InteractionStatus
    from ugc_bot.infrastructure.db.models import (
        LegacyFinancialCaseModel,
        LegacyFinancialGuardModel,
        UserReferralBindingModel,
    )

    (
        factory,
        service,
        (manager, other_partner, advertiser, first, second, order),
    ) = manager_pg
    async with factory.begin() as db:
        await db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == order)
            .values(bloggers_needed=2)
        )
        await db.execute(
            update(OfferDispatchModel)
            .where(OfferDispatchModel.order_id == order)
            .values(in_offer=True)
        )
        db.add_all(
            [
                UserReferralBindingModel(
                    referrer_user_id=partner,
                    referred_user_id=creator,
                    created_at=datetime.now(timezone.utc),
                )
                for partner, creator in (
                    (manager, first),
                    (other_partner, second),
                )
            ]
        )
    request, _, _ = _api_dependencies(factory, service)
    with (
        patch.object(
            api, "_ensure_user_and_get_id", AsyncMock(return_value=manager)
        ),
        patch.object(
            api, "notify_admins_about_complaint", AsyncMock()
        ) as notify,
    ):
        for creator in (first, second, second):
            await api.manager_feedback(
                request,
                order,
                creator,
                api.ManagerFeedbackRequest(
                    init_data="synthetic",
                    status="issue",
                    issue_description=f"Problem on creator {creator}",
                ),
            )
    async with factory() as db:
        claims = list(
            (
                await db.scalars(
                    select(InteractionModel).where(
                        InteractionModel.order_id == order
                    )
                )
            ).all()
        )
        assert len(claims) == 2
        assert all(claim.status == InteractionStatus.ISSUE for claim in claims)
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ComplaintModel)
                .where(ComplaintModel.order_id == order)
            )
            == 2
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(LegacyFinancialCaseModel)
                .where(
                    LegacyFinancialCaseModel.interaction_id.in_(
                        [claim.interaction_id for claim in claims]
                    )
                )
            )
            == 2
        )
        guards = list(
            (
                await db.scalars(
                    select(LegacyFinancialGuardModel).where(
                        LegacyFinancialGuardModel.interaction_id.in_(
                            [claim.interaction_id for claim in claims]
                        )
                    )
                )
            ).all()
        )
        assert {guard.user_id for guard in guards} == {manager, other_partner}
    assert notify.await_count == 2
