"""Paid capture, real assignment/lifecycle, production factories and ledger."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, inspect, select, update
from sqlalchemy.orm import Session

from tests.helpers.financial_worker import process_until_published
from tests.postgres_financial.test_v1_capture import (
    capture_env,
    telegram_receipt,
)
from ugc_bot.application.collaboration_ports import CollaborationCommand
from ugc_bot.application.financial_delivery_ownership import (
    SEPARATE_DELIVERY_EVENT_TYPES,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    OutboxEventStatus,
    UserStatus,
)
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ManagerOrderModel,
    OrderItemModel,
    OutboxEventModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.item_assignments import (
    SqlAlchemyItemAssignmentRepository,
)
from ugc_bot.outbox_processor import OutboxProcessor

__all__ = ["capture_env"]


class Clock:
    def __init__(self, at):
        self.at = at


def test_work_assessment_schema_is_migrated(financial_pg_engine):
    assert (
        "financial_work_assessments"
        in inspect(financial_pg_engine).get_table_names()
    )


async def start_flow(
    env,
    monkeypatch,
    *,
    referred=True,
    accompaniment=120000,
    same_manager_partner=False,
    before_capture=None,
):
    creator, manager, partner = [uuid4() for _ in range(3)]
    if same_manager_partner:
        partner = manager
    with Session(env["pg"]) as db, db.begin():
        db.add_all(
            [
                UserModel(
                    user_id=uid,
                    messenger_type=MessengerType.TELEGRAM,
                    username="synthetic-work",
                    status=UserStatus.ACTIVE,
                    created_at=datetime.now(timezone.utc) - timedelta(days=5),
                )
                for uid in dict.fromkeys((creator, manager, partner))
            ]
        )
        db.flush()
        db.add_all(
            [
                AdvertiserProfileModel(
                    user_id=env["client"], contact="synthetic"
                ),
                BloggerProfileModel(
                    user_id=creator,
                    instagram_url="https://instagram.com/" + creator.hex,
                    instagram_user_id=creator.hex,
                    confirmed=True,
                    topics={},
                    audience_gender=AudienceGender.ALL,
                    audience_age_min=18,
                    audience_age_max=65,
                    audience_geo="synthetic",
                    price=1,
                ),
                ManagerOrderModel(
                    user_id=manager,
                    order_id=env["order"],
                    created_at=datetime.now(timezone.utc),
                ),
            ]
        )
        db.add(
            UserReferralBindingModel(
                referrer_user_id=partner, referred_user_id=env["client"]
            )
        )
        if referred:
            db.add(
                UserReferralBindingModel(
                    referrer_user_id=partner, referred_user_id=creator
                )
            )
    if before_capture is not None:
        before_capture(partner, creator)
    receipt = replace(
        telegram_receipt(env), protocol_message_at=datetime.now(timezone.utc)
    )
    await env["service"].confirm_telegram_payment(
        env["client"],
        env["order"],
        receipt.provider_payment_charge_id,
        receipt.total_amount,
        receipt.currency,
        receipt=receipt,
    )
    clock = Clock(datetime.now(timezone.utc) + timedelta(seconds=1))
    monkeypatch.setattr(SystemClock, "now", lambda self: clock.at)
    with Session(env["pg"]) as db:
        item = db.scalar(
            select(OrderItemModel.paid_item_id).where(
                OrderItemModel.order_id == env["order"],
                OrderItemModel.accompaniment_minor == accompaniment,
            )
        )
    async with env["factory"].begin() as db:
        assignment = await SqlAlchemyItemAssignmentRepository().replace(
            paid_item_id=item,
            expected_version=0,
            creator_id=creator,
            manager_id=manager,
            actor_id=env["client"],
            reason="client-authorized actual assignment",
            at=clock.at,
            session=db,
        )
        assignment_id = assignment.assignment_id
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": env["pg"].url.render_as_string(hide_password=False),
            "DB_POOL_SIZE": 4,
            "FINANCIAL_CORE_ENABLED": True,
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
        }
    )
    container = Container(config)
    env.setdefault("_work_containers", []).append(container)
    services = container.build_bot_services()
    lifecycle = services["collaboration_service"]
    publisher, _ = container.build_outbox_deps()
    worker = OutboxProcessor(publisher, None)

    async def command(action, actor, version, **changes):
        async with container.transaction_manager.transaction() as db:
            return await lifecycle.execute(
                CollaborationCommand(
                    assignment_id=assignment_id,
                    action=action,
                    operation_key=action + ":" + str(version),
                    actor_id=actor,
                    expected_version=version,
                    **changes,
                ),
                session=db,
            )

    await command(
        "assign",
        env["client"],
        0,
        due_at=clock.at + timedelta(days=2),
        terms_reference="brief:client agreed creator scope and due date",
    )
    return dict(
        container=container,
        worker=worker,
        command=command,
        clock=clock,
        creator=creator,
        manager=manager,
        partner=partner,
        item=item,
        assignment=assignment_id,
        receipt=receipt,
        publisher=publisher,
    )


@pytest_asyncio.fixture(autouse=True)
async def dispose_work_containers(capture_env):
    yield
    for container in capture_env.get("_work_containers", ()):
        await container.dispose()


def obligations(env):
    table = Base.metadata.tables["financial_obligations"]
    with Session(env["pg"]) as db:
        return (
            db.execute(select(table).where(table.c.order_id == env["order"]))
            .mappings()
            .all()
        )


def wallet(env, recipient):
    table = Base.metadata.tables["financial_wallets"]
    with Session(env["pg"]) as db:
        return (
            db.execute(select(table).where(table.c.recipient_id == recipient))
            .mappings()
            .one()
        )


async def process_work_events(env, flow):
    with Session(env["pg"]) as db:
        targets = tuple(
            db.scalars(
                select(OutboxEventModel.event_id).where(
                    OutboxEventModel.aggregate_id.in_(
                        (str(env["order"]), str(flow["assignment"]))
                    ),
                    OutboxEventModel.event_type.like("financial.%"),
                    OutboxEventModel.event_type.not_in(
                        SEPARATE_DELIVERY_EVENT_TYPES
                    ),
                )
            )
        )
    await process_until_published(flow["worker"], env["pg"], targets)


@pytest.mark.asyncio
@pytest.mark.parametrize("earlier_pending", [0, 100])
async def test_actual_capture_assignment_claim_and_agreement_produce_hold(
    capture_env, monkeypatch, earlier_pending
):
    env = capture_env
    if earlier_pending:
        # Earlier negative fixtures can fill a whole production claim batch.
        with Session(env["pg"]) as db, db.begin():
            db.add_all(
                OutboxEventModel(
                    event_id=uuid4(),
                    event_type="financial.fixture_boundary",
                    aggregate_id=str(uuid4()),
                    aggregate_type="synthetic_boundary",
                    payload={},
                    status=OutboxEventStatus.PENDING,
                    created_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
                    retry_count=0,
                )
                for _ in range(earlier_pending)
            )
    flow = await start_flow(env, monkeypatch)
    await process_work_events(env, flow)
    first = obligations(env)
    assert len([r for r in first if r["kind"] == "client_referral"]) == 2
    creator = next(r for r in first if r["kind"] == "creator_referral")
    assert (
        creator["base_minor"] == 50000
        and creator["recipient_id"] == flow["partner"]
    )
    assert not any(r["kind"] == "management" for r in first)
    assert wallet(env, flow["partner"])["pending_minor"] == 15000
    await flow["command"]("start", env["client"], 1)
    await flow["command"](
        "claim", flow["creator"], 2, evidence="actual creator proof"
    )
    await flow["command"]("agree", env["client"], 3)
    await process_work_events(env, flow)
    assert wallet(env, flow["partner"])["hold_minor"] == 5000
    assert wallet(env, flow["partner"])["pending_minor"] == 10000
    assert wallet(env, flow["manager"])["hold_minor"] == 60000
    assert (
        next(r for r in obligations(env) if r["kind"] == "management")[
            "base_minor"
        ]
        == 60000
    )
    with Session(env["pg"]) as db:
        snapshots = Base.metadata.tables["rate_snapshots"]
        row = (
            db.execute(
                select(snapshots).where(
                    snapshots.c.id == creator["snapshot_id"]
                )
            )
            .mappings()
            .one()
        )
        assert row["effective_at"] == flow["receipt"].protocol_message_at
        assert row["verified_count"] == 1


async def finish_work(env, flow):
    await flow["command"]("start", env["client"], 1)
    await flow["command"]("claim", flow["creator"], 2, evidence="actual proof")
    return await flow["command"]("agree", env["client"], 3)


def event_for(env, assignment, kind):
    from ugc_bot.infrastructure.db.repositories.outbox import (
        _to_outbox_event_entity,
    )

    with Session(env["pg"]) as db:
        row = db.scalars(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(assignment),
                OutboxEventModel.event_type
                == "financial.collaboration." + kind,
            )
        ).one()
        return _to_outbox_event_entity(row)


def work_handler(flow):
    return flow["publisher"].financial_delivery.financial_router.handlers[
        "financial.collaboration.assigned"
    ]


@pytest.mark.asyncio
async def test_earned_manager_survives_removal_and_matures_from_schedule(
    capture_env, monkeypatch
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    await finish_work(env, flow)
    await process_work_events(env, flow)
    assert wallet(env, flow["manager"])["hold_minor"] == 60000
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            delete(ManagerOrderModel).where(
                ManagerOrderModel.order_id == env["order"],
                ManagerOrderModel.user_id == flow["manager"],
            )
        )
    flow["clock"].at += timedelta(days=14)
    await flow["command"](
        "advance", None, 4, system_actor="collaboration_scheduler"
    )
    await process_work_events(env, flow)
    assert wallet(env, flow["manager"])["available_minor"] == 60000
    assert wallet(env, flow["partner"])["available_minor"] == 5000
    assert wallet(env, flow["partner"])["pending_minor"] == 10000
    assert wallet(env, flow["manager"])["hold_minor"] == 0
    async with flow["container"].transaction_manager.transaction() as db:
        repo = flow["container"].build_repos()["financial_ledger_repo"]
        issued = await repo.get_issue(
            next(
                r["business_key"]
                for r in obligations(env)
                if r["kind"] == "management"
            ),
            session=db,
        )
        assert issued.basis.actor_kind == "system"
        assert issued.basis.actor_id is None
        assert issued.basis.system_actor == "work_entitlement"
        assert issued.basis.available_at is None
        maturity = await repo.get_maturity(issued.obligation_id, session=db)
        assert (
            maturity.success_final_at + timedelta(days=14)
            == maturity.release_at
        )


@pytest.mark.asyncio
async def test_actual_dispute_blocks_client_and_creator_despite_event_lag(
    capture_env, monkeypatch
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    await process_work_events(env, flow)
    await flow["command"]("start", env["client"], 1)
    await flow["command"]("claim", flow["creator"], 2, evidence="proof")
    await flow["command"]("dispute", env["client"], 3, reason="wrong content")
    stale = event_for(env, flow["assignment"], "started")
    async with flow["container"].transaction_manager.transaction() as db:
        await work_handler(flow).handle(stale, session=db)
    assert wallet(env, flow["partner"])["blocked_minor"] == 10000
    assert wallet(env, flow["partner"])["pending_minor"] == 5000
    with Session(env["pg"]) as db:
        inbox = Base.metadata.tables["financial_work_assessments"]
        assessment = db.execute(
            select(inbox.c.assessment).where(inbox.c.event_id == stale.event_id)
        ).scalar_one()
        disputed = event_for(env, flow["assignment"], "disputed")
        assert (
            db.scalar(
                select(inbox.c.event_id).where(
                    inbox.c.event_id == disputed.event_id
                )
            )
            is None
        )
        movements = Base.metadata.tables["financial_movements"]
        blocks = (
            db.execute(
                select(movements).where(
                    movements.c.case_id == assessment["case_id"]
                )
            )
            .mappings()
            .all()
        )
        assert len(blocks) == 2
        assert all(r["actor_kind"] == "system" for r in blocks)
    await process_work_events(env, flow)
    assert wallet(env, flow["partner"])["blocked_minor"] == 10000


@pytest.mark.asyncio
async def test_real_expiry_cancels_work_but_preserves_paid_selection(
    capture_env, monkeypatch
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    await process_work_events(env, flow)
    flow["clock"].at += timedelta(days=16)
    await flow["command"](
        "advance", None, 1, system_actor="collaboration_scheduler"
    )
    await process_work_events(env, flow)
    assert wallet(env, flow["partner"])["cancelled_minor"] == 5000
    assert wallet(env, flow["partner"])["pending_minor"] == 10000
    assert not any(r["kind"] == "management" for r in obligations(env))


@pytest.mark.asyncio
async def test_known_absent_creator_produces_system_audit_without_fake_grade(
    capture_env, monkeypatch
):
    env = capture_env
    flow = await start_flow(env, monkeypatch, referred=False)
    await process_work_events(env, flow)
    source = event_for(env, flow["assignment"], "assigned")
    assert source.status.value == "published", source.last_error
    assert all(r["kind"] == "client_referral" for r in obligations(env))
    with Session(env["pg"]) as db:
        audit = Base.metadata.tables["financial_audit_events"]
        potential = (
            db.execute(
                select(audit).where(
                    audit.c.action == "potential_basis",
                    audit.c.system_actor == "work_entitlement",
                )
            )
            .mappings()
            .one()
        )
        assert (
            potential["actor_kind"] == "system"
            and potential["actor_id"] is None
        )
        assert potential["details"]["recipient_id"] is None
        assert potential["details"]["verified_count"] is None
        assert potential["details"]["registered_at"] is None


@pytest.mark.asyncio
async def test_unfunded_accompaniment_never_earns_management(
    capture_env, monkeypatch
):
    env = capture_env
    flow = await start_flow(env, monkeypatch, accompaniment=0)
    await finish_work(env, flow)
    await process_work_events(env, flow)
    assert (
        len([r for r in obligations(env) if r["kind"] == "creator_referral"])
        == 1
    )
    assert not any(r["kind"] == "management" for r in obligations(env))
    with Session(env["pg"]) as db:
        inbox = Base.metadata.tables["financial_work_assessments"]
        assessments = db.scalars(
            select(inbox.c.assessment).where(
                inbox.c.assignment_id == flow["assignment"]
            )
        ).all()
        assert all(
            a["manager"] == "accompaniment_not_purchased" for a in assessments
        )


@pytest.mark.asyncio
async def test_assessment_and_money_rollback_together(capture_env, monkeypatch):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    event = event_for(env, flow["assignment"], "assigned")
    handler = work_handler(flow)
    real = handler.repository.save_receipt

    async def fail(*args, **kwargs):
        await real(*args, **kwargs)
        raise RuntimeError("synthetic_after_inbox")

    monkeypatch.setattr(handler.repository, "save_receipt", fail)
    with pytest.raises(RuntimeError, match="synthetic_after_inbox"):
        async with flow["container"].transaction_manager.transaction() as db:
            await handler.handle(event, session=db)
    assert not obligations(env)
    with Session(env["pg"]) as db:
        inbox = Base.metadata.tables["financial_work_assessments"]
        assert (
            db.scalar(
                select(inbox.c.event_id).where(
                    inbox.c.event_id == event.event_id
                )
            )
            is None
        )
        wallets = Base.metadata.tables["financial_wallets"]
        assert (
            db.execute(
                select(wallets).where(
                    wallets.c.recipient_id.in_(
                        [flow["partner"], flow["manager"]]
                    )
                )
            ).first()
            is None
        )
    monkeypatch.setattr(handler.repository, "save_receipt", real)
    await process_work_events(env, flow)
    assert len(obligations(env)) == 3


@pytest.mark.asyncio
async def test_concurrent_delivery_has_one_assessment_and_one_issuance(
    capture_env, monkeypatch
):
    import asyncio

    env = capture_env
    flow = await start_flow(env, monkeypatch)
    event = event_for(env, flow["assignment"], "assigned")
    handler = work_handler(flow)
    original = handler.repository.load
    discovered = asyncio.Event()
    calls = 0

    async def load(event, *, session):
        nonlocal calls
        value = await original(event, session=session)
        calls += 1
        if calls <= 2:
            if calls == 2:
                discovered.set()
            await asyncio.wait_for(discovered.wait(), timeout=5)
        return value

    monkeypatch.setattr(handler.repository, "load", load)

    async def consume():
        async with flow["container"].transaction_manager.transaction() as db:
            await handler.handle(event, session=db)

    await asyncio.wait_for(asyncio.gather(consume(), consume()), timeout=10)
    assert len(obligations(env)) == 1
    assert wallet(env, flow["partner"])["pending_minor"] == 5000
    with Session(env["pg"]) as db:
        inbox = Base.metadata.tables["financial_work_assessments"]
        assert (
            len(
                db.scalars(
                    select(inbox.c.event_id).where(
                        inbox.c.assignment_id == flow["assignment"]
                    )
                ).all()
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("part", ["payload", "scope", "identity"])
async def test_forged_pointer_never_issues_or_records_receipt(
    capture_env, monkeypatch, part
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    event = event_for(env, flow["assignment"], "assigned")
    if part == "payload":
        forged = replace(
            event, payload={"collaboration_event_id": str(uuid4())}
        )
    elif part == "scope":
        forged = replace(event, aggregate_id=str(uuid4()))
    else:
        forged = replace(event, event_id=uuid4())
    with pytest.raises(
        ValueError, match="work_source_mismatch|capture_funding_missing"
    ):
        async with flow["container"].transaction_manager.transaction() as db:
            await work_handler(flow).handle(forged, session=db)
    assert not obligations(env)


@pytest.mark.asyncio
async def test_payment_history_survives_later_profile_and_referral_change(
    capture_env, monkeypatch
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == flow["creator"])
            .values(confirmed=False)
        )
        db.execute(
            delete(UserReferralBindingModel).where(
                UserReferralBindingModel.referred_user_id == flow["creator"]
            )
        )
    await process_work_events(env, flow)
    creator = next(
        r for r in obligations(env) if r["kind"] == "creator_referral"
    )
    assert creator["recipient_id"] == flow["partner"]
    with Session(env["pg"]) as db:
        rates = Base.metadata.tables["rate_snapshots"]
        rate = (
            db.execute(
                select(rates).where(rates.c.id == creator["snapshot_id"])
            )
            .mappings()
            .one()
        )
        assert rate["verified_count"] == 1
        assert rate["effective_at"] == flow["receipt"].protocol_message_at


@pytest.mark.asyncio
async def test_work_assessment_cannot_be_rewritten_or_removed(
    capture_env, monkeypatch
):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    env = capture_env
    flow = await start_flow(env, monkeypatch)
    await process_work_events(env, flow)
    for statement in (
        "UPDATE financial_work_assessments SET source_hash=source_hash",
        "DELETE FROM financial_work_assessments",
        "TRUNCATE financial_work_assessments",
    ):
        with (
            pytest.raises(
                IntegrityError, match="financial_work_assessment_immutable"
            ),
            Session(env["pg"]) as db,
            db.begin(),
        ):
            db.execute(text(statement))
    event = event_for(env, flow["assignment"], "assigned")
    async with flow["container"].transaction_manager.transaction() as db:
        receipt = await work_handler(flow).repository.get_receipt(
            event.event_id, session=db
        )
        assert receipt["source_hash"]
