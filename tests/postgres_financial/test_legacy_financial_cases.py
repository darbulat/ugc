"""Operational legacy cases on migrated, private PostgreSQL schemas."""

from dataclasses import replace

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_legacy_dispute_payout_guard import (
    seed_available_income,
)
from ugc_bot.domain.enums import InteractionStatus
from ugc_bot.infrastructure.db.repositories.interactions import (
    SqlAlchemyInteractionRepository,
)


@pytest_asyncio.fixture
async def cases_factory(financial_pg_engine):
    engine = create_async_engine(financial_pg_engine.url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_first_issue_persists_case_without_complaint_description(
    cases_factory,
):
    _, interaction = await seed_available_income(cases_factory)
    repo = SqlAlchemyInteractionRepository(cases_factory)
    await repo.save(replace(interaction, status=InteractionStatus.ISSUE))
    async with cases_factory() as db:
        case = (
            await db.execute(
                text(
                    "SELECT source, cause, version, released FROM "
                    "legacy_financial_cases WHERE interaction_id=:id"
                ),
                {"id": interaction.interaction_id},
            )
        ).one()
        assert case == ("legacy_interaction", "feedback_issue", 1, False)
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM legacy_financial_case_events WHERE "
                    "interaction_id=:id"
                ),
                {"id": interaction.interaction_id},
            )
            == 1
        )


@pytest.mark.asyncio
async def test_authorized_no_adjustment_release_is_audited_and_keeps_income(
    cases_factory,
):
    from uuid import uuid4

    from sqlalchemy import select, update

    from ugc_bot.application.services.legacy_financial_case_service import (
        LegacyFinancialCaseService,
    )
    from ugc_bot.infrastructure.db.models import (
        ReferralIncomeEntryModel,
        UserModel,
    )
    from ugc_bot.infrastructure.db.repositories.legacy_financial_cases import (
        SqlAlchemyLegacyFinancialCaseRepository,
    )
    from ugc_bot.infrastructure.db.repositories.legacy_financial_guards import (
        SqlAlchemyLegacyFinancialGuardRepository,
    )

    recipient, interaction = await seed_available_income(cases_factory)
    await SqlAlchemyInteractionRepository(cases_factory).save(
        replace(interaction, status=InteractionStatus.ISSUE)
    )
    async with cases_factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == interaction.advertiser_id)
            .values(admin=True)
        )
        before = (
            await db.execute(
                select(ReferralIncomeEntryModel.__table__).where(
                    ReferralIncomeEntryModel.order_id == interaction.order_id
                )
            )
        ).all()
    service = LegacyFinancialCaseService(
        SqlAlchemyLegacyFinancialCaseRepository(cases_factory)
    )
    command = uuid4()
    result = await service.review(
        interaction.interaction_id,
        actor_id=interaction.advertiser_id,
        expected_version=1,
        command_id=command,
        decision="release_no_adjustment",
        reason="Confirmed delivered legacy result; reconciled unchanged",
        confirmed_result=True,
    )
    assert result["released"] is True
    assert result["version"] == 2
    assert (
        await service.review(
            interaction.interaction_id,
            actor_id=interaction.advertiser_id,
            expected_version=1,
            command_id=command,
            decision="release_no_adjustment",
            reason="Confirmed delivered legacy result; reconciled unchanged",
            confirmed_result=True,
        )
        == result
    )
    await SqlAlchemyLegacyFinancialGuardRepository(
        cases_factory
    ).assert_payout_allowed(recipient, "RUB")
    async with cases_factory() as db:
        after = (
            await db.execute(
                select(ReferralIncomeEntryModel.__table__).where(
                    ReferralIncomeEntryModel.order_id == interaction.order_id
                )
            )
        ).all()
        assert before == after
        events = (
            await db.execute(
                text(
                    "SELECT actor_id, decision, reason, version FROM "
                    "legacy_financial_case_events WHERE interaction_id=:id "
                    "ORDER BY version"
                ),
                {"id": interaction.interaction_id},
            )
        ).all()
        assert len(events) == 2
        assert events[-1] == (
            interaction.advertiser_id,
            "release_no_adjustment",
            "Confirmed delivered legacy result; reconciled unchanged",
            2,
        )


@pytest.mark.asyncio
async def test_old_issue_survives_ordinary_status_edit(cases_factory):
    from ugc_bot.application.errors import LegacyPayoutBlockedError
    from ugc_bot.infrastructure.db.repositories.interactions import (
        _to_interaction_model,
    )
    from ugc_bot.infrastructure.db.repositories.legacy_financial_guards import (
        SqlAlchemyLegacyFinancialGuardRepository,
    )

    recipient, interaction = await seed_available_income(cases_factory)
    async with cases_factory.begin() as db:
        db.add(
            _to_interaction_model(
                replace(interaction, status=InteractionStatus.ISSUE)
            )
        )
    await SqlAlchemyInteractionRepository(cases_factory).save(
        replace(interaction, status=InteractionStatus.OK)
    )
    with pytest.raises(LegacyPayoutBlockedError):
        await SqlAlchemyLegacyFinancialGuardRepository(
            cases_factory
        ).assert_payout_allowed(recipient, "RUB")


@pytest.mark.asyncio
async def test_new_issue_reopens_but_ordinary_issue_save_does_not(
    cases_factory,
):
    from uuid import uuid4

    from sqlalchemy import update

    from ugc_bot.application.errors import LegacyPayoutBlockedError
    from ugc_bot.application.services.legacy_financial_case_service import (
        LegacyFinancialCaseService,
    )
    from ugc_bot.infrastructure.db.models import UserModel
    from ugc_bot.infrastructure.db.repositories.legacy_financial_cases import (
        SqlAlchemyLegacyFinancialCaseRepository,
    )
    from ugc_bot.infrastructure.db.repositories.legacy_financial_guards import (
        SqlAlchemyLegacyFinancialGuardRepository,
    )

    recipient, interaction = await seed_available_income(cases_factory)
    issue = replace(
        interaction, status=InteractionStatus.ISSUE, from_blogger="⚠️ Проблема"
    )
    repo = SqlAlchemyInteractionRepository(cases_factory)
    await repo.save(issue)
    async with cases_factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == interaction.advertiser_id)
            .values(admin=True)
        )
    service = LegacyFinancialCaseService(
        SqlAlchemyLegacyFinancialCaseRepository(cases_factory)
    )
    await service.review(
        interaction.interaction_id,
        actor_id=interaction.advertiser_id,
        expected_version=1,
        command_id=uuid4(),
        decision="release_no_adjustment",
        reason="Confirmed legacy delivery; no correction",
        confirmed_result=True,
    )
    await repo.save(issue)
    await SqlAlchemyLegacyFinancialGuardRepository(
        cases_factory
    ).assert_payout_allowed(recipient, "RUB")
    await repo.save(replace(issue, from_advertiser="⚠️ Новая проблема"))
    with pytest.raises(LegacyPayoutBlockedError):
        await SqlAlchemyLegacyFinancialGuardRepository(
            cases_factory
        ).assert_payout_allowed(recipient, "RUB")
    async with cases_factory() as db:
        assert (
            await db.execute(
                text(
                    "SELECT version,released FROM legacy_financial_cases WHERE "
                    "interaction_id=:id"
                ),
                {"id": interaction.interaction_id},
            )
        ).one() == (3, False)


@pytest.mark.asyncio
async def test_old_issue_is_visible_and_reviewable_without_ordinary_edit(
    cases_factory,
):
    from sqlalchemy import update

    from ugc_bot.infrastructure.db.models import UserModel
    from ugc_bot.infrastructure.db.repositories.interactions import (
        _to_interaction_model,
    )
    from ugc_bot.infrastructure.db.repositories.legacy_financial_cases import (
        SqlAlchemyLegacyFinancialCaseRepository,
    )

    recipient, interaction = await seed_available_income(cases_factory)
    async with cases_factory.begin() as db:
        db.add(
            _to_interaction_model(
                replace(interaction, status=InteractionStatus.ISSUE)
            )
        )
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == interaction.advertiser_id)
            .values(admin=True)
        )
    repo = SqlAlchemyLegacyFinancialCaseRepository(cases_factory)
    visible = await repo.list_cases(
        interaction.advertiser_id, interaction.interaction_id
    )
    assert len(visible) == 1
    assert visible[0]["wallets"] == [
        {"user_id": str(recipient), "currency": "RUB"}
    ]
    async with cases_factory() as db:
        assert (
            await db.scalar(
                text(
                    "SELECT version FROM legacy_financial_cases WHERE "
                    "interaction_id=:id"
                ),
                {"id": interaction.interaction_id},
            )
            == 1
        )


async def review_setup(factory):
    from sqlalchemy import update

    from ugc_bot.application.services.legacy_financial_case_service import (
        LegacyFinancialCaseService,
    )
    from ugc_bot.infrastructure.db.models import UserModel
    from ugc_bot.infrastructure.db.repositories.legacy_financial_cases import (
        SqlAlchemyLegacyFinancialCaseRepository,
    )

    recipient, interaction = await seed_available_income(factory)
    await SqlAlchemyInteractionRepository(factory).save(
        replace(interaction, status=InteractionStatus.ISSUE)
    )
    async with factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == interaction.advertiser_id)
            .values(admin=True)
        )
    return (
        recipient,
        interaction,
        LegacyFinancialCaseService(
            SqlAlchemyLegacyFinancialCaseRepository(factory)
        ),
    )


async def release(service, interaction, **overrides):
    from uuid import uuid4

    args = dict(
        actor_id=interaction.advertiser_id,
        expected_version=1,
        command_id=uuid4(),
        decision="release_no_adjustment",
        reason="Confirmed delivered legacy result; unchanged money",
        confirmed_result=True,
    )
    args.update(overrides)
    return await service.review(interaction.interaction_id, **args)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "nonadmin",
        "forged",
        "reason",
        "stale",
        "unconfirmed",
        "unknown_income",
        "negative_income",
        "unknown_payout",
        "negative_wallet",
    ],
)
async def test_unsafe_review_fails_closed_without_audit_or_money_changes(
    cases_factory, failure
):
    from decimal import Decimal
    from uuid import uuid4

    from sqlalchemy import delete, update

    from ugc_bot.domain.enums import PayoutRequestStatus
    from ugc_bot.infrastructure.db.models import (
        PayoutRequestModel,
        ReferralIncomeEntryModel,
    )

    recipient, interaction, service = await review_setup(cases_factory)
    overrides = {}
    error = ValueError
    if failure == "nonadmin":
        overrides["actor_id"] = recipient
        error = PermissionError
    elif failure == "forged":
        overrides["actor_id"] = uuid4()
        error = PermissionError
    elif failure == "reason":
        overrides["reason"] = "   "
    elif failure == "stale":
        overrides["expected_version"] = 999
    elif failure == "unconfirmed":
        overrides["confirmed_result"] = False
    async with cases_factory.begin() as db:
        if failure == "unknown_income":
            await db.execute(
                delete(ReferralIncomeEntryModel).where(
                    ReferralIncomeEntryModel.order_id == interaction.order_id
                )
            )
        if failure == "negative_income":
            await db.execute(
                update(ReferralIncomeEntryModel)
                .where(
                    ReferralIncomeEntryModel.order_id == interaction.order_id
                )
                .values(commission_amount=Decimal("-1"))
            )
        if failure in {"unknown_payout", "negative_wallet"}:
            db.add(
                PayoutRequestModel(
                    request_id=uuid4(),
                    user_id=recipient,
                    currency="RUB",
                    status=PayoutRequestStatus.PAID,
                    amount=None
                    if failure == "unknown_payout"
                    else Decimal("51"),
                )
            )
    async with cases_factory() as db:
        income_before = (
            await db.execute(
                text(
                    "SELECT * FROM referral_income_entries WHERE order_id=:id"
                ),
                {"id": interaction.order_id},
            )
        ).all()
        paid_before = (
            await db.execute(
                text("SELECT * FROM payout_requests WHERE user_id=:id"),
                {"id": recipient},
            )
        ).all()
    with pytest.raises(error):
        await release(service, interaction, **overrides)
    async with cases_factory() as db:
        assert (
            await db.execute(
                text(
                    "SELECT version,released FROM legacy_financial_cases WHERE "
                    "interaction_id=:id"
                ),
                {"id": interaction.interaction_id},
            )
        ).one() == (1, False)
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM legacy_financial_case_events WHERE "
                    "interaction_id=:id"
                ),
                {"id": interaction.interaction_id},
            )
            == 1
        )
        assert (
            await db.execute(
                text(
                    "SELECT * FROM referral_income_entries WHERE order_id=:id"
                ),
                {"id": interaction.order_id},
            )
        ).all() == income_before
        assert (
            await db.execute(
                text("SELECT * FROM payout_requests WHERE user_id=:id"),
                {"id": recipient},
            )
        ).all() == paid_before


@pytest.mark.asyncio
async def test_selective_release_preserves_paid_and_currency(
    cases_factory,
):
    from decimal import Decimal
    from uuid import uuid4

    from ugc_bot.application.errors import LegacyPayoutBlockedError
    from ugc_bot.domain.enums import OrderStatus, PayoutRequestStatus
    from ugc_bot.infrastructure.db.models import (
        OrderModel,
        PayoutRequestModel,
        ReferralIncomeEntryModel,
    )
    from ugc_bot.infrastructure.db.repositories.legacy_financial_guards import (
        SqlAlchemyLegacyFinancialGuardRepository,
    )

    recipient, first, service = await review_setup(cases_factory)
    second = replace(
        first,
        interaction_id=uuid4(),
        order_id=uuid4(),
        status=InteractionStatus.ISSUE,
    )
    async with cases_factory.begin() as db:
        db.add(
            OrderModel(
                order_id=second.order_id,
                advertiser_id=second.advertiser_id,
                product_link="https://example.invalid",
                offer_text="Synthetic",
                price=500,
                bloggers_needed=1,
                status=OrderStatus.CLOSED,
                currency="RUB",
            )
        )
        await db.flush()
        db.add(
            ReferralIncomeEntryModel(
                entry_id=uuid4(),
                referrer_user_id=recipient,
                referred_user_id=second.blogger_id,
                order_id=second.order_id,
                income_type="creator",
                currency="RUB",
                platform_revenue=Decimal("500"),
                commission_rate=Decimal("0.1"),
                commission_amount=Decimal("50"),
            )
        )
        db.add(
            PayoutRequestModel(
                request_id=uuid4(),
                user_id=recipient,
                currency="RUB",
                status=PayoutRequestStatus.PAID,
                amount=Decimal("35"),
            )
        )
    await SqlAlchemyInteractionRepository(cases_factory).save(second)
    async with cases_factory() as db:
        income_before = (
            await db.execute(
                text(
                    "SELECT * FROM referral_income_entries WHERE "
                    "referrer_user_id=:id ORDER BY entry_id"
                ),
                {"id": recipient},
            )
        ).all()
        paid_before = (
            await db.execute(
                text("SELECT * FROM payout_requests WHERE user_id=:id"),
                {"id": recipient},
            )
        ).all()
    await release(service, first)
    guards = SqlAlchemyLegacyFinancialGuardRepository(cases_factory)
    with pytest.raises(LegacyPayoutBlockedError):
        await guards.assert_payout_allowed(recipient, "RUB")
    await guards.assert_payout_allowed(recipient, "USD")
    await release(service, second)
    await guards.assert_payout_allowed(recipient, "RUB")
    async with cases_factory() as db:
        assert (
            await db.execute(
                text(
                    "SELECT * FROM referral_income_entries WHERE "
                    "referrer_user_id=:id ORDER BY entry_id"
                ),
                {"id": recipient},
            )
        ).all() == income_before
        assert (
            await db.execute(
                text("SELECT * FROM payout_requests WHERE user_id=:id"),
                {"id": recipient},
            )
        ).all() == paid_before


@pytest.mark.asyncio
async def test_review_waits_on_common_wallet_lock(cases_factory):
    import asyncio

    from sqlalchemy import select

    from ugc_bot.infrastructure.db.models import UserModel

    recipient, interaction, service = await review_setup(cases_factory)
    async with cases_factory.begin() as db:
        await db.execute(
            select(UserModel)
            .where(UserModel.user_id == recipient)
            .with_for_update()
        )
        task = asyncio.create_task(release(service, interaction))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(task), 0.2)
    assert (await asyncio.wait_for(task, 5))["released"] is True


@pytest.mark.asyncio
async def test_issue_and_review_serialize_on_interaction_then_wallet(
    cases_factory,
):
    import asyncio

    recipient, interaction, service = await review_setup(cases_factory)
    async with cases_factory.begin() as db:
        await SqlAlchemyInteractionRepository(cases_factory).save(
            replace(
                interaction,
                status=InteractionStatus.ISSUE,
                from_blogger="⚠️ New source fact",
            ),
            session=db,
        )
        task = asyncio.create_task(release(service, interaction))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(task), 0.2)
    with pytest.raises(ValueError, match="Stale"):
        await asyncio.wait_for(task, 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["blocked", "deleted"])
async def test_disabled_admin_cannot_release_even_with_retained_admin_flag(
    cases_factory, status
):
    from sqlalchemy import select, update

    from ugc_bot.domain.enums import UserStatus
    from ugc_bot.infrastructure.db.models import (
        LegacyFinancialCaseModel,
        UserModel,
    )

    _, interaction, service = await review_setup(cases_factory)
    async with cases_factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == interaction.advertiser_id)
            .values(status=UserStatus(status))
        )
    with pytest.raises(PermissionError, match="admin"):
        await release(service, interaction)
    async with cases_factory() as db:
        case = await db.scalar(
            select(LegacyFinancialCaseModel).where(
                LegacyFinancialCaseModel.interaction_id
                == interaction.interaction_id
            )
        )
        assert case.released is False
        assert case.version == 1
