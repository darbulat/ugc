"""Synthetic corrections use actual intake, invoice and capture producers."""

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.postgres_financial.test_client_entitlement_runtime import (
    seed_attribution,
)
from tests.postgres_financial.test_order_intake import command, service
from tests.postgres_financial.test_v1_capture import telegram_receipt
from ugc_bot.application.correction_ports import RequestSelectionRefund
from ugc_bot.application.services.creator_identity_history_service import (
    CreatorIdentityHistoryService,
)
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicyService,
)
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.repositories.financial_capture import (
    SqlAlchemyFinancialCaptureRepository,
)


async def captured_order(
    env, *, referred=True, mode="self_service", existing=None
):
    request = (
        command(env, service_mode=mode) if existing is None else existing[0]
    )
    result = (
        await service(env).create(request) if existing is None else existing[1]
    )
    client = env["user"].user_id
    partner, stranger = seed_attribution(
        dict(pg=env["pg"], client=client), referred=referred
    )
    payments = env["container"].build_bot_services()["payment_service"]
    payments.capture_repository = SqlAlchemyFinancialCaptureRepository(
        FinancialPolicyService(env["config"].financial),
        history=CreatorIdentityHistoryService(
            env["repos"]["creator_identity_history_repo"]
        ),
    )
    payments.capture_account = "synthetic-correction-merchant"
    async with env["container"].transaction_manager.transaction() as db:
        await payments.capture_repository.issue(
            result.order_id, client, payments.capture_account, session=db
        )
    receipt = telegram_receipt(
        dict(now=env["clock"].at, order=result.order_id),
        total_amount=result.total_minor,
    )
    receipt = replace(receipt, protocol_message_at=datetime.now(timezone.utc))
    payment = await payments.confirm_telegram_payment(
        client,
        result.order_id,
        receipt.provider_payment_charge_id,
        receipt.total_amount,
        receipt.currency,
        receipt=receipt,
    )
    env["clock"].at = request.selection_due_at + timedelta(seconds=1)
    return dict(
        order=result,
        request=request,
        payment=payment,
        client=client,
        partner=partner,
        stranger=stranger,
        capture_at=receipt.protocol_message_at,
    )


def refund_command(facts, *, actor_id=None, items=None):
    return RequestSelectionRefund(
        actor_id=actor_id or facts["client"],
        operation_key="synthetic-refund:" + uuid4().hex,
        reason="Agreed selection deadline expired",
        order_id=facts["order"].order_id,
        paid_item_ids=items
        or tuple(i.paid_item_id for i in facts["order"].items[-5:]),
        expected_source_hash="a" * 64,
    )


def rows(env, name, **where):
    table = Base.metadata.tables[name]
    with Session(env["pg"]) as db:
        return [
            dict(row)
            for row in db.execute(select(table).filter_by(**where)).mappings()
        ]


def plain(value):
    from ugc_bot.application.collaboration_ports import canonical

    return canonical(asdict(value))


async def assess_original(env, facts):
    from ugc_bot.application.services.client_entitlement_service import (
        ClientEntitlementService,
    )
    from ugc_bot.application.services.financial_ledger_service import (
        FinancialLedgerService,
    )
    from ugc_bot.infrastructure.db.models import OutboxEventModel
    from ugc_bot.infrastructure.db.repositories.outbox import (
        _to_outbox_event_entity,
    )

    repo = env["repos"]
    consumer = ClientEntitlementService(
        repo["client_entitlement_repo"],
        FinancialLedgerService(repo["financial_ledger_repo"]),
        CreatorIdentityHistoryService(repo["creator_identity_history_repo"]),
        repo["rate_override_repo"],
        env["clock"],
    )
    async with env["container"].transaction_manager.transaction() as db:
        event = await db.scalar(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(facts["order"].order_id),
                OutboxEventModel.event_type
                == "financial.client_snapshot_requested",
            )
        )
        await consumer.handle(_to_outbox_event_entity(event), session=db)


async def deliver_original_positions(env, facts, *, count=25):
    """Actual selection/delivery producers with a local receipt transport."""
    from sqlalchemy import update

    from ugc_bot.application.notice_delivery_ports import DeliveryReceipt
    from ugc_bot.application.services.paid_selection_delivery import (
        PaidSelectionDelivery,
    )
    from ugc_bot.application.services.paid_selection_interest import (
        PaidSelectionInterestService,
    )
    from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
    from ugc_bot.infrastructure.clock import SystemClock
    from ugc_bot.infrastructure.db.models import (
        BloggerProfileModel,
        OrderModel,
        UserModel,
    )
    from ugc_bot.infrastructure.db.repositories.paid_selection import (
        SqlAlchemyPaidSelectionRepository,
    )
    from ugc_bot.infrastructure.db.repositories.paid_selection_delivery import (
        SqlAlchemyPaidSelectionDeliveryRepository,
    )

    creators = tuple(uuid4() for _ in range(count))
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == facts["order"].order_id)
            .values(status=OrderStatus.ACTIVE)
        )
        for creator in creators:
            db.add(
                UserModel(
                    user_id=creator,
                    username="synthetic-creator",
                    telegram_id=str(creator.int % 10**12 + 1),
                    messenger_type=MessengerType.TELEGRAM,
                    status=UserStatus.ACTIVE,
                )
            )
        db.flush()
        for creator in creators:
            db.add(
                BloggerProfileModel(
                    user_id=creator,
                    instagram_url="https://instagram.com/" + creator.hex,
                    instagram_user_id=creator.hex,
                    confirmed=True,
                    topics={},
                    audience_gender="all",
                    audience_age_min=18,
                    audience_age_max=40,
                    audience_geo="synthetic",
                    price=1,
                )
            )

    class LocalReceiptTransport:
        async def send(self, message):
            assert (
                env["container"].session_factory.kw["bind"].pool.checkedout()
                == 0
            )
            return DeliveryReceipt(
                "telegram", "synthetic-local-transport:" + uuid4().hex
            )

    tm = env["container"].transaction_manager
    interest = PaidSelectionInterestService(
        SqlAlchemyPaidSelectionRepository(), tm, SystemClock(), enabled=True
    )
    delivery = PaidSelectionDelivery(
        SqlAlchemyPaidSelectionDeliveryRepository(),
        tm,
        LocalReceiptTransport(),
        SystemClock(),
    )
    selected = []
    for creator in creators:
        response = await interest.respond(facts["order"].order_id, creator)
        assert response.accepted
        attempt = await delivery.prepare(response.job_id)
        assert attempt is not None
        await delivery.deliver(attempt)
        selected.append(response.paid_item_id)
    return tuple(selected)


async def approved_match(env, facts, repo, db, *, selected=None):
    from ugc_bot.application.correction_ports import correction_command_hash
    from ugc_bot.domain.corrections import CorrectionEvent, CorrectionState

    command = refund_command(facts, items=selected)
    scope = await repo.discover_scope(command, session=db)
    assert scope.available, scope.unavailable_reason
    await repo.lock_scope(scope, session=db)
    command = replace(command, expected_source_hash=scope.source_hash)
    await repo.save_command(
        command,
        correction_command_hash(command),
        {"synthetic": True},
        session=db,
    )
    receipt = await repo.command(
        command.actor_id, command.operation_key, session=db
    )
    command_id = receipt["command_id"]
    case_id, request_id, intent, observation, match = (
        uuid4() for _ in range(5)
    )
    at = env["clock"].at
    bundle = plain(scope.bundle)["components"]
    await repo.append_fact(
        "cases",
        dict(
            case_id=case_id,
            command_id=command_id,
            order_id=scope.order_id,
            client_id=scope.client_id,
            recorded_at=at,
        ),
        session=db,
    )
    await repo.append_fact(
        "requests",
        dict(
            request_id=request_id,
            case_id=case_id,
            command_id=command_id,
            order_id=scope.order_id,
            client_id=scope.client_id,
            paid_item_ids=[str(i) for i in scope.selected_paid_item_ids],
            source_hash=scope.source_hash,
            bundle=bundle,
            recorded_at=at,
        ),
        session=db,
    )
    await repo.append_fact(
        "intents",
        dict(
            intent_id=intent,
            case_id=case_id,
            command_id=command_id,
            request_id=request_id,
            capture_id=scope.capture_id,
            payment_id=scope.payment_id,
            source_hash=scope.source_hash,
            bundle=bundle,
            amount_minor=scope.bundle.total_minor,
            currency="RUB",
            review_version=1,
            recorded_at=at,
        ),
        session=db,
    )
    state = CorrectionState(
        case_id=case_id,
        version=1,
        source_hash=scope.source_hash,
        request_status="requested",
        review_status="approved",
    )
    await repo.append_event(
        CorrectionEvent(
            event_id=uuid4(),
            case_id=case_id,
            version=1,
            command_id=command_id,
            source_id=intent,
            source_hash=scope.source_hash,
            actor_id=env["admin"].user_id,
            reason="Synthetic exact scope review",
            evidence_reference="synthetic:review",
            evidence_hash="b" * 64,
            recorded_at=at,
            previous_state_hash=None,
            result_state=state,
            result_state_hash=state.payload_hash,
        ),
        session=db,
    )
    await repo.append_fact(
        "observations",
        dict(
            observation_id=observation,
            case_id=case_id,
            intent_id=intent,
            command_id=command_id,
            known_order_id=scope.order_id,
            known_capture_intent_id=scope.intent_id,
            original_payment_reference=facts["payment"].external_id,
            bank_account_label="synthetic operator account",
            bank_reference="synthetic-bank:" + observation.hex,
            amount_minor=scope.bundle.total_minor,
            currency="RUB",
            occurred_at=at,
            reported_component="selection",
            provenance="manual_admin_observation",
            evidence_reference="synthetic:bank-observation",
            evidence_hash="c" * 64,
            recorded_at=at,
        ),
        session=db,
    )
    await repo.append_fact(
        "matches",
        dict(
            match_id=match,
            case_id=case_id,
            command_id=command_id,
            intent_id=intent,
            observation_id=observation,
            order_id=scope.order_id,
            capture_id=scope.capture_id,
            payment_id=scope.payment_id,
            source_hash=scope.source_hash,
            bundle=bundle,
            amount_minor=scope.bundle.total_minor,
            currency="RUB",
            review_version=1,
            recorded_at=at,
        ),
        session=db,
    )
    return dict(
        scope=scope,
        case_id=case_id,
        match_id=match,
        intent_id=intent,
        observation_id=observation,
        command_id=command_id,
    )


async def append_application(
    env,
    facts,
    repo,
    match,
    db,
    *,
    omit_last=False,
    mutate_liability=None,
    skip_projection=False,
):
    from ugc_bot.application.financial_ports import JournalMovement
    from ugc_bot.infrastructure.db.repositories.financial_ledger import (
        SqlAlchemyFinancialLedgerRepository,
    )

    scope = match["scope"]
    application = uuid4()
    await repo.append_fact(
        "applications",
        dict(
            application_id=application,
            match_id=match["match_id"],
            intent_id=match["intent_id"],
            case_id=match["case_id"],
            order_id=scope.order_id,
            payment_id=scope.payment_id,
            capture_id=scope.capture_id,
            source_hash=scope.source_hash,
            amount_minor=scope.bundle.total_minor,
            currency="RUB",
            recorded_at=env["clock"].at,
        ),
        session=db,
    )
    ledger = SqlAlchemyFinancialLedgerRepository()
    components = (
        scope.bundle.components[:-1] if omit_last else scope.bundle.components
    )
    for part in components:
        component_id = uuid4()
        await repo.append_fact(
            "components",
            dict(
                component_application_id=component_id,
                application_id=application,
                allocation_key=part.allocation_key,
                payment_id=part.payment_id,
                paid_item_id=part.paid_item_id,
                component="selection",
                currency="RUB",
                gross_minor=part.gross_minor,
                prior_refund_minor=0,
                new_refund_minor=part.gross_minor,
                refund_minor=part.gross_minor,
            ),
            session=db,
        )
        key = f"client-selection:{scope.payment_id}:{part.paid_item_id}"
        original = await ledger.get_issue(key, session=db)
        values = dict(
            assessment_id=uuid4(),
            component_application_id=component_id,
            business_key=key,
            target_minor=0,
            already_cancelled_minor=0,
            delta_minor=0,
        )
        if original is None:
            audit = Base.metadata.tables["financial_audit_events"]
            potential = await db.scalar(
                select(audit.c.id).where(
                    audit.c.operation_key == "potential:" + key
                )
            )
            values.update(status="covered_absence", potential_id=potential)
        else:
            issuance = await ledger.get_entry_ref("issue:" + key, session=db)
            movement = JournalMovement(
                obligation_id=original.obligation_id,
                operation_key="synthetic-cancel:"
                + str(application)
                + ":"
                + str(part.paid_item_id),
                event_id=str(scope.capture_id),
                movement_type="reversal",
                amount_minor=original.movement.amount_minor,
                currency="RUB",
                effective_at=env["clock"].at,
                recorded_at=env["clock"].at,
                actor_id=env["admin"].user_id,
                actor_kind="admin",
                reason="Synthetic pending source cancellation",
                bucket_from="pending",
                bucket_to="cancelled",
                source_entry_id=issuance,
                case_id=match["case_id"],
                refund_id=application,
            )
            await ledger.append(movement, session=db)
            if not skip_projection:
                await ledger.apply_projection(movement, session=db)
            actual = await ledger.get_entry_ref(
                movement.operation_key, session=db
            )
            values.update(
                status="pending_cancelled",
                obligation_id=original.obligation_id,
                snapshot_id=original.snapshot_id,
                issuance_entry_id=issuance,
                frozen_rate_bps=original.basis.rate_bps,
                override_id=original.basis.override_id,
                target_minor=movement.amount_minor,
                delta_minor=movement.amount_minor,
                movement_id=actual,
            )
        if mutate_liability:
            values.update(mutate_liability(values))
        await repo.append_fact("liabilities", values, session=db)
    return application


def manual_observation(env, facts):
    """Retain a reported order without choosing a refundable item subset."""
    from ugc_bot.application.correction_ports import (
        RecordManualRefundObservation,
    )
    from ugc_bot.infrastructure.db.repositories.financial_capture import (
        intent_id,
    )

    payment = facts.get("payment")
    return RecordManualRefundObservation(
        actor_id=env["admin"].user_id,
        operation_key="synthetic-unselected:" + uuid4().hex,
        reason="Retain synthetic scoped actual observation",
        case_id=None,
        known_order_id=facts["order"].order_id,
        known_capture_intent_id=intent_id(facts["order"].order_id),
        original_payment_reference=payment.external_id if payment else "",
        bank_account_label="synthetic account",
        bank_reference="synthetic:unselected:" + uuid4().hex,
        amount_minor=250_000,
        currency="RUB",
        occurred_at=env["clock"].at,
        reported_component="selection",
        evidence_reference="synthetic:observation",
        evidence_hash="a" * 64,
        expected_version=None,
    )


async def retain_case_only_report(env, facts, repo, *, known_client):
    """Retain a case without inferring routing or nullable facts."""
    from ugc_bot.application.correction_ports import correction_command_hash

    report = replace(
        manual_observation(env, facts),
        case_id=uuid4(),
        known_order_id=None,
        known_capture_intent_id=None,
    )
    async with env["container"].transaction_manager.transaction() as db:
        await repo.save_command(
            report,
            correction_command_hash(report),
            {"synthetic": True},
            session=db,
        )
        command = await repo.command(
            report.actor_id, report.operation_key, session=db
        )
        await repo.append_fact(
            "cases",
            dict(
                case_id=report.case_id,
                command_id=command["command_id"],
                client_id=facts["client"] if known_client else None,
                order_id=facts["order"].order_id if known_client else None,
                recorded_at=env["clock"].at,
            ),
            session=db,
        )
    return report
