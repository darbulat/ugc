"""Actual capture, immutable reserve interest and journal compensation."""

import asyncio
import os
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.test_paid_selection_interest import (
    capture,
    capture_env,
    seed_creators,
    service,
)
from ugc_bot.application.financial_ports import IssueBasis, JournalMovement
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.replacement_ports import (
    ReplacementContact,
    ReplacementDecision,
    ReplacementRequest,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)
from ugc_bot.application.services.obligation_compensation_service import (
    ObligationCompensationService,
)
from ugc_bot.application.services.replacement_service import ReplacementService
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import (
    ItemAssignmentModel,
    OrderItemModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.replacement_models import TABLES
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)
from ugc_bot.infrastructure.db.repositories.replacements import (
    SqlAlchemyReplacementRepository,
)

__all__ = ["capture_env"]


@pytest.fixture(scope="module")
def financial_pg_engine():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated PostgreSQL test database is required")
    with isolated_financial_database(
        url,
        target_revision="0114_refund_replacements",
        current_order_model=True,
    ) as engine:
        yield engine


async def setup(env):
    creators = seed_creators(env, count=4)
    await capture(env)
    interests = [
        await service(env).respond(env["order"], creator)
        for creator in creators
    ]
    admin = uuid4()
    with Session(env["pg"]) as db, db.begin():
        client_native = str(env["client"].int % 10**12 + 1)
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["client"])
            .values(telegram_id=client_native)
        )
        db.add(
            UserModel(
                user_id=admin,
                status="active",
                admin=True,
                messenger_type="telegram",
                telegram_id=str(admin.int % 10**12 + 1),
                username="synthetic admin",
            )
        )
        payment = db.scalar(
            select(PaymentModel).where(PaymentModel.order_id == env["order"])
        )
        paid_at, payment_id = payment.paid_at, payment.payment_id
    ledger = FinancialLedgerService(SqlAlchemyFinancialLedgerRepository())
    app = ReplacementService(
        SqlAlchemyReplacementRepository(),
        ledger,
        ObligationCompensationService(ledger),
        SystemClock(),
        enabled=True,
    )
    client_proof = AuthenticatedMessengerPrincipal(
        env["client"], "telegram", client_native
    )
    admin_proof = AuthenticatedMessengerPrincipal(
        admin, "telegram", str(admin.int % 10**12 + 1)
    )
    original = interests[0]
    basis = IssueBasis(
        business_key="replacement-old:" + str(original.assignment_id),
        kind="creator_referral",
        recipient_id=env["client"],
        paid_item_id=original.paid_item_id,
        order_id=env["order"],
        assignment_id=original.assignment_id,
        referred_user_id=creators[0],
        payment_id=payment_id,
        currency="RUB",
        base_minor=env.get("selection_minor", 50000),
        rate_bps=1000,
        policy_version=env["version"],
        snapshot_at=paid_at,
        registered_at=paid_at - timedelta(days=1),
        verified_count=0,
        event_id="synthetic-original",
        reason="Original pending creator obligation",
        actor_id=admin,
    )
    async with env["factory"].begin() as db:
        issue = await ledger.issue(basis, recorded_at=paid_at, session=db)
    return app, interests, issue, client_proof, admin_proof


async def submit(env, app, interests, principal, *, key="request", candidate=2):
    command = ReplacementRequest(
        key,
        principal.user_id,
        interests[0].paid_item_id,
        1,
        interests[candidate].interest_id,
        "refusal",
        "Автор отказался",
        "support:refusal",
    )
    async with env["factory"].begin() as db:
        return await app.request(command, principal=principal, session=db)


def decision(pending, principal, *, key="approve", exception=True):
    return ReplacementDecision(
        key,
        principal.user_id,
        UUID(pending["request_id"]),
        1,
        "approve",
        "Отказ проверен",
        "support:verified",
        exception_reason="Дополнительная замена согласована"
        if exception
        else None,
        exception_evidence="agreement:replacement" if exception else None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("bucket", ["pending", "available"])
async def test_real_reserve_cancels_before_assignment_without_new_paid_position(
    capture_env,
    bucket,
):
    env = capture_env
    app, interests, issue, client, admin = await setup(env)
    if bucket == "available":
        async with env["factory"].begin() as db:
            for before, after in (("pending", "hold"), ("hold", "available")):
                movement = JournalMovement(
                    obligation_id=issue.obligation_id,
                    operation_key="synthetic:"
                    + str(issue.obligation_id)
                    + ":"
                    + after,
                    event_id="synthetic-journal-history",
                    movement_type="transfer",
                    amount_minor=5000,
                    currency="RUB",
                    effective_at=issue.basis.snapshot_at,
                    recorded_at=issue.basis.snapshot_at,
                    actor_id=admin.user_id,
                    reason="Synthetic existing journal history",
                    bucket_from=before,
                    bucket_to=after,
                )
                await app.ledger.repository.append(movement, session=db)
                await app.ledger.repository.apply_projection(
                    movement, session=db
                )
    pending = await submit(env, app, interests, client)
    async with env["factory"].begin() as db:
        view = await app.view(
            client.user_id,
            interests[0].paid_item_id,
            principal=client,
            session=db,
        )
        assert {row["interest_id"] for row in view["candidates"]} == {
            str(i.interest_id) for i in interests[2:]
        }
        assert view["history"][0]["state"] == "pending"
        queued = await app.queue(admin.user_id, principal=admin, session=db)
        assert pending["request_id"] in {
            row["request_id"] for row in queued["entries"]
        }
    command = decision(pending, admin)
    async with env["factory"].begin() as db:
        with pytest.raises(
            ValueError, match="replacement_reserve_exception_required"
        ):
            await app.decide(
                replace(
                    command, exception_reason=None, exception_evidence=None
                ),
                principal=admin,
                session=db,
            )
    async with env["factory"].begin() as db:
        result = await app.decide(command, principal=admin, session=db)
        report = await FinancialReconciliationService(
            app.ledger.repository
        ).require_ready(env["client"], "RUB", session=db)
        assert (
            report.replay.by_obligation[issue.obligation_id]["cancelled"]
            == 5000
        )
        assert report.replay.by_obligation[issue.obligation_id]["pending"] == 0
        assert await app.decide(command, principal=admin, session=db) == result
        view = await app.view(
            client.user_id,
            interests[0].paid_item_id,
            principal=client,
            session=db,
        )
        assert (
            view["history"][0]["state"] == "approved"
            and view["history"][0]["current"] is True
        )
    assert result["original_paid_pool"] == 2 and result["reserve_limit"] == 0
    assert (
        result["billable_positions_added"] == 0
        and result["reserve_exception"] is True
    )
    with Session(env["pg"]) as db:
        old = db.get(ItemAssignmentModel, interests[0].assignment_id)
        new = db.get(ItemAssignmentModel, UUID(result["assignment_id"]))
        assert (
            old.valid_to is not None
            and new.valid_to is None
            and new.version == 2
        )
        assert new.creator_id == interests[2].creator_id
        assert (
            db.scalar(
                select(func.count())
                .select_from(OrderItemModel)
                .where(OrderItemModel.order_id == env["order"])
            )
            == 2
        )
        interest_table = Base.metadata.tables["paid_selection_interests"]
        reserve = (
            db.execute(
                select(interest_table).where(
                    interest_table.c.interest_id == interests[2].interest_id
                )
            )
            .mappings()
            .one()
        )
        assert reserve["accepted"] is False and reserve["assignment_id"] is None
    async with env["factory"].begin() as db:
        contact_command = ReplacementContact(
            "contact",
            client.user_id,
            UUID(result["replacement_id"]),
            "Получить контакт замены",
            "miniapp:explicit",
        )
        contact = await app.contact(
            contact_command, principal=client, session=db
        )
        assert contact["contact"]["creator_id"] == str(interests[2].creator_id)
        assert (
            await app.contact(contact_command, principal=client, session=db)
            == contact
        )
    second_request = ReplacementRequest(
        "second-request",
        client.user_id,
        interests[0].paid_item_id,
        2,
        interests[3].interest_id,
        "refusal",
        "Замена тоже отказалась",
        "support:second",
    )
    async with env["factory"].begin() as db:
        second_pending = await app.request(
            second_request, principal=client, session=db
        )
        second = await app.decide(
            decision(second_pending, admin, key="second-approve"),
            principal=admin,
            session=db,
        )
        assert (
            second["assignment_version"] == 3
            and second["replacement_count"] == 2
        )
        assert second["cancelled_movement_ids"] == []
        assert (
            await app.contact(contact_command, principal=client, session=db)
            == contact
        )
    with pytest.raises(ValueError, match="replacement_assignment_obsolete"):
        async with env["factory"].begin() as db:
            await app.contact(
                replace(contact_command, operation_key="fresh-old-contact"),
                principal=client,
                session=db,
            )
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(TABLES["contacts"])
                .where(
                    TABLES["contacts"].c.replacement_id
                    == UUID(result["replacement_id"])
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(
                    Base.metadata.tables["paid_selection_accepted_deliveries"]
                )
                .where(
                    Base.metadata.tables[
                        "paid_selection_accepted_deliveries"
                    ].c.order_id
                    == env["order"]
                )
            )
            == 0
        )
    with pytest.raises(IntegrityError), env["pg"].begin() as db:
        db.execute(
            text(
                "UPDATE paid_replacement_decisions SET reason='changed' "
                "WHERE replacement_id=:id"
            ),
            {"id": UUID(result["replacement_id"])},
        )


@pytest.mark.asyncio
async def test_concurrent_reviews_one_allocation_and_current_auth_before_replay(
    capture_env,
):
    env = capture_env
    app, interests, _, client, admin = await setup(env)
    pending = await submit(env, app, interests, client)
    command = decision(pending, admin)
    engine = create_async_engine(env["pg"].url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def approve():
        async with factory.begin() as db:
            return await app.decide(command, principal=admin, session=db)

    try:
        results = await asyncio.wait_for(
            asyncio.gather(approve(), approve()), timeout=20
        )
        assert results[0] == results[1]
        with Session(env["pg"]) as db, db.begin():
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(TABLES["allocations"])
                    .where(
                        TABLES["allocations"].c.paid_item_id
                        == interests[0].paid_item_id
                    )
                )
                == 1
            )
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == admin.user_id)
                .values(admin=False)
            )
        with pytest.raises(PermissionError, match="active_admin_required"):
            async with factory.begin() as db:
                await app.decide(command, principal=admin, session=db)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_actual_success_event_forbids_replacement_after_request(
    capture_env,
):
    from ugc_bot.application.collaboration_ports import CollaborationCommand
    from ugc_bot.application.services.collaboration_service import (
        CollaborationService,
    )
    from ugc_bot.infrastructure.db.repositories.collaborations import (
        SqlAlchemyCollaborationRepository,
    )

    env = capture_env
    app, interests, _, client, admin = await setup(env)
    pending = await submit(env, app, interests, client)
    work = CollaborationService(
        SqlAlchemyCollaborationRepository(), SystemClock()
    )
    for version, (action, actor, extra) in enumerate(
        (
            (
                "assign",
                client.user_id,
                dict(
                    due_at=SystemClock().now() + timedelta(days=1),
                    terms_reference="client-consented:1",
                ),
            ),
            ("start", client.user_id, {}),
            (
                "claim",
                interests[0].creator_id,
                dict(evidence="https://example.test/completed-work"),
            ),
            ("agree", client.user_id, {}),
        )
    ):
        async with env["factory"].begin() as db:
            await work.execute(
                CollaborationCommand(
                    assignment_id=interests[0].assignment_id,
                    action=action,
                    actor_id=actor,
                    operation_key="work:" + action,
                    expected_version=version,
                    **extra,
                ),
                session=db,
            )
    with pytest.raises(
        ValueError, match="replacement_after_completed_work_forbidden"
    ):
        async with env["factory"].begin() as db:
            await app.decide(
                decision(pending, admin), principal=admin, session=db
            )
    with Session(env["pg"]) as db:
        assert (
            db.get(ItemAssignmentModel, interests[0].assignment_id).valid_to
            is None
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(TABLES["decisions"])
                .where(
                    TABLES["decisions"].c.request_id
                    == UUID(pending["request_id"])
                )
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_actual_signed_native_replacement_api_uses_current_sql_auth(
    capture_env, platform
):
    import httpx
    from fastapi import FastAPI

    from tests.e2e.miniapp_helpers import generate_init_data
    from ugc_bot.config import AppConfig
    from ugc_bot.container import Container
    from ugc_bot.miniapp.api import router

    env = capture_env
    _, interests, _, client, admin = await setup(env)
    with Session(env["pg"]) as db, db.begin():
        for proof in (client, admin):
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == proof.user_id)
                .values(max_id=proof.external_id)
            )
    config = AppConfig.model_validate(
        dict(
            BOT_TOKEN="test-token",
            MAX_BOT_TOKEN="test-token",
            DATABASE_URL=env["pg"].url.render_as_string(hide_password=False),
            FINANCIAL_CORE_ENABLED=True,
            KAFKA_ENABLED=False,
            USE_REDIS_STORAGE=False,
            REDIS_URL="",
        )
    )
    container = Container(config)
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = config
    app.state.dispatcher = container.build_bot_services()

    def signed(proof):
        return dict(
            init_data=generate_init_data(
                "test-token", int(proof.external_id), "synthetic"
            ),
            platform=platform,
        )

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as wire:
            body = dict(
                **signed(client),
                operation_key="signed-request",
                paid_item_id=str(interests[0].paid_item_id),
                expected_assignment_version=1,
                candidate_interest_id=str(interests[2].interest_id),
                reason_code="refusal",
                reason="Отказ автора",
                evidence_reference="support:signed",
            )
            forged = await wire.post(
                "/miniapp/api/financial/replacements/request",
                json={**body, "actor_id": str(admin.user_id)},
            )
            assert (
                forged.status_code == 422
                and forged.headers["cache-control"] == "no-store"
            )
            requested = await wire.post(
                "/miniapp/api/financial/replacements/request", json=body
            )
            assert requested.status_code == 200, requested.text
            decision_body = dict(
                **signed(admin),
                operation_key="signed-approve",
                request_id=requested.json()["request_id"],
                expected_version=1,
                action="approve",
                reason="Основания проверены",
                evidence_reference="review:signed",
                exception_reason="Дополнительная замена согласована",
                exception_evidence="agreement:signed",
            )
            approved = await wire.post(
                "/miniapp/api/financial/replacements/decision",
                json=decision_body,
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["billable_positions_added"] == 0
            with Session(env["pg"]) as db, db.begin():
                db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == admin.user_id)
                    .values(admin=False)
                )
            denied = await wire.post(
                "/miniapp/api/financial/replacements/decision",
                json=decision_body,
            )
            assert (
                denied.status_code == 403
                and denied.json()["detail"] == "active_admin_required"
            )
    finally:
        await container.dispose()
