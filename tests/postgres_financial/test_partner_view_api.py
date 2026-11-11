"""Own-only partner reads through signed ASGI and real production SQL wiring."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_collaboration_persistence import (
    collaboration_pg as collaboration_fixture,
)
from tests.postgres_financial.test_lifecycle_ledger_persistence import basis
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    FinancialWalletModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)
from ugc_bot.miniapp.api import router

collaboration_pg = collaboration_fixture
PATH = "/miniapp/api/partner/view"


def application(container, config):
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = config
    app.state.dispatcher = container.build_bot_services()
    return app


async def setup(pg, actor_role, platform):
    factory, _, _, clock, data = pg
    actor = data[actor_role]
    external = str(uuid4().int % 10**12 + 1)
    async with factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == actor)
            .values(
                messenger_type=MessengerType(platform),
                telegram_id=external if platform == "telegram" else None,
                max_id=external if platform == "max" else None,
                referral_code=actor.hex[:12],
                language="en",
            )
        )
        await db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == data["creator"])
            .values(instagram_user_id="ig-" + str(data["creator"]))
        )
        if actor_role != "creator":
            db.add(
                UserReferralBindingModel(
                    referrer_user_id=actor,
                    referred_user_id=data["creator"],
                    created_at=clock.at - timedelta(days=1),
                )
            )
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "MAX_BOT_TOKEN": "test-token",
            "DATABASE_URL": factory.kw["bind"].url.render_as_string(
                hide_password=False
            ),
            "FINANCIAL_CORE_ENABLED": False,
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
            "REFERRAL_BOT_USERNAME": "synthetic_umc_bot",
            "MAX_REFERRAL_BOT_USERNAME": "synthetic_umc_max",
        }
    )
    container = Container(config)
    body = {
        "init_data": generate_init_data(
            "test-token", int(external), "private-username"
        ),
        "platform": platform,
    }
    return container, config, body


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("actor_role", ["client", "creator", "manager"])
async def test_partner_read_all_roles_hosts_core_off_without_wallet_creation(
    collaboration_pg, platform, actor_role
):
    container, config, body = await setup(
        collaboration_pg, actor_role, platform
    )
    factory, _, _, _, data = collaboration_pg
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application(container, config)),
            base_url="http://testserver",
        ) as client:
            result = await client.post(PATH, json=body)
            assert result.status_code == 200, result.text
            view = result.json()
            assert view["actor_id"] == str(data[actor_role])
            assert view["writes_paused"] is True
            assert view["financial"]["state"] == "uninitialized"
            assert view["financial"]["balances"] is None
            assert view["grade"]["verified_creators"] == (
                0 if actor_role == "creator" else 1
            )
            expected = (
                "https://t.me/synthetic_umc_bot"
                if platform == "telegram"
                else "https://max.ru/synthetic_umc_max"
            )
            code = data[actor_role].hex[:12]
            assert view["referral"]["link"] == expected + "?start=ref_" + code
            assert (
                "private-username" not in result.text
                and "contact" not in result.text
            )
            if actor_role != "creator":
                member = view["network"]["members"][0]
                assert member["member_id"] == str(data["creator"])
                assert member["socials"][0]["verified"] is True
                assert member["socials"][0]["followers_count"] is None
            for forged in (
                {"recipient_id": str(data["client"])},
                {"actor_id": str(data["manager"])},
                {"user_id": str(data["creator"])},
                {"network_page": -1},
            ):
                assert (
                    await client.post(PATH, json={**body, **forged})
                ).status_code == 422
        async with factory.begin() as db:
            assert (
                await db.scalar(
                    select(FinancialWalletModel).where(
                        FinancialWalletModel.recipient_id == data[actor_role]
                    )
                )
                is None
            )
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_partner_history_uses_actual_snapshot_and_excludes_private_reason(
    collaboration_pg,
):
    container, config, body = await setup(
        collaboration_pg, "client", "telegram"
    )
    factory, _, _, clock, data = collaboration_pg
    repo = SqlAlchemyFinancialLedgerRepository()
    source = await basis(collaboration_pg)
    source = replace(source, reason="PRIVATE CASE EVIDENCE: never expose this")
    async with factory.begin() as db:
        await FinancialLedgerService(repo).issue(
            source, recorded_at=clock.at, session=db
        )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application(container, config)),
            base_url="http://testserver",
        ) as client:
            result = await client.post(PATH, json=body)
            assert result.status_code == 200, result.text
            finance = result.json()["financial"]
            assert finance["state"] == "ready"
            assert finance["balances"]["pending"] == "5000"
            history = finance["history"]["entries"]
            assert len(history) == 1
            assert history[0]["order_id"] == str(data["order"])
            assert history[0]["base_minor"] == "50000"
            assert history[0]["rate_bps"] == 1000
            assert history[0]["amount_minor"] == "5000"
            assert history[0]["kind"] == "creator_referral"
            assert "PRIVATE CASE" not in result.text
            assert {g["kind"] for g in finance["groups"]} == {
                "client_referral",
                "creator_referral",
                "management",
            }
        async with factory.begin() as db:
            await db.execute(
                update(FinancialWalletModel)
                .where(FinancialWalletModel.recipient_id == data["client"])
                .values(pending_minor=9999)
            )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application(container, config)),
            base_url="http://testserver",
        ) as client:
            result = await client.post(PATH, json=body)
            assert result.status_code == 200
            assert result.json()["financial"]["state"] == "mismatch"
            assert result.json()["financial"]["balances"]["pending"] == "5000"
            assert result.json()["financial"]["projection"]["pending"] == "9999"
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_own_network_identity_counts_and_pending_only_name_owned_members(
    collaboration_pg,
):
    from tests.postgres_financial.test_collaboration_persistence import (
        command,
        execute,
        start,
    )

    container, config, body = await setup(
        collaboration_pg, "client", "telegram"
    )
    factory, _, _, clock, data = collaboration_pg
    current = await start(collaboration_pg)
    app = application(container, config)
    app.state.dispatcher["partner_view_service"].clock = clock
    async with factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == data["creator"])
            .values(
                username="Own invited author",
                telegram="own_invited_author",
                created_at=clock.at - timedelta(days=2),
            )
        )
        await FinancialLedgerService(
            SqlAlchemyFinancialLedgerRepository()
        ).issue(await basis(collaboration_pg), recorded_at=clock.at, session=db)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            result = await client.post(PATH, json=body)
            assert result.status_code == 200, result.text
            member = result.json()["network"]["members"][0]
            assert member["telegram_username"] == "own_invited_author"
            assert member["work"] == {"active_orders": 1, "completed_works": 0}
            pending = result.json()["financial"]["pending"]["entries"][0]
            assert pending["reason"] == "awaiting_confirmation"
            assert pending["waiting_for"] == [
                {
                    "role": "client",
                    "display_name": None,
                    "telegram_username": None,
                },
                {
                    "role": "creator",
                    "display_name": "Own invited author",
                    "telegram_username": "own_invited_author",
                },
            ]
            assert result.json()["capabilities"]["manage_overrides"] is False
            await execute(
                factory,
                collaboration_pg[1],
                command(
                    data,
                    "claim",
                    "creator",
                    current.version,
                    evidence="https://example.test/private-proof",
                ),
            )
            claimed = await client.post(PATH, json=body)
            waiting = claimed.json()["financial"]["pending"]["entries"][0]
            assert waiting["reason"] == "confirmation_notice_pending"
            assert waiting["waiting_for"] == [
                {
                    "role": "client",
                    "display_name": None,
                    "telegram_username": None,
                }
            ]
            assert "private-proof" not in claimed.text
            from ugc_bot.infrastructure.db.models import ItemAssignmentModel

            async with factory.begin() as db:
                await db.execute(
                    update(ItemAssignmentModel)
                    .where(ItemAssignmentModel.creator_id == data["creator"])
                    .values(valid_to=clock.at)
                )
            historical = await client.post(PATH, json=body)
            assert historical.json()["network"]["members"][0]["work"] == {
                "active_orders": 0,
                "completed_works": 0,
            }
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("observed", [None, 0])
async def test_partner_public_metrics_keep_latest_known_canonical_provenance(
    collaboration_pg,
    observed,
):
    from ugc_bot.domain.enums import WorkFormat
    from ugc_bot.infrastructure.db.models import InstagramStatsModel
    from ugc_bot.infrastructure.db.social_models import SocialAccountModel

    container, config, body = await setup(
        collaboration_pg, "client", "telegram"
    )
    factory, _, _, clock, data = collaboration_pg
    async with factory.begin() as db:
        db.add(
            InstagramStatsModel(
                user_id=data["creator"],
                instagram_id="ig-" + str(data["creator"]),
                raw_response={"private_payload": "never expose"},
                followers_count=4321,
                provider="observed-provider",
                fetched_at=clock.at,
            )
        )
        db.add(
            SocialAccountModel(
                account_id=uuid4(),
                user_id=data["creator"],
                platform="instagram",
                url="https://instagram.com/synthetic_creator",
                handle="synthetic_creator",
                verified=True,
                external_id="ig-" + str(data["creator"]),
                work_format=WorkFormat.UGC_ONLY,
                verification_observed_at=clock.at,
                verification_source="canonical_verification",
                followers_count=observed,
                metrics_source="newer-observation"
                if observed is not None
                else None,
                metrics_fetched_at=clock.at + timedelta(seconds=1)
                if observed is not None
                else None,
                created_at=clock.at,
                updated_at=clock.at,
            )
        )
        db.add(
            SocialAccountModel(
                account_id=uuid4(),
                user_id=data["creator"],
                platform="tiktok",
                url="https://tiktok.com/@synthetic_creator",
                handle="synthetic_creator",
                verified=False,
                work_format=WorkFormat.UGC_ONLY,
                created_at=clock.at,
                updated_at=clock.at,
            )
        )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application(container, config)),
            base_url="http://testserver",
        ) as client:
            result = await client.post(PATH, json=body)
            assert result.status_code == 200, result.text
            account = result.json()["network"]["members"][0]["socials"][0]
            assert account["followers_count"] == (
                4321 if observed is None else 0
            )
            assert account["metrics_source"] == (
                "observed-provider" if observed is None else "newer-observation"
            )
            assert account["verification_source"] == "canonical_verification"
            assert "private_payload" not in result.text
            supplemental = result.json()["network"]["members"][0]["socials"][1]
            assert supplemental["platform"] == "tiktok"
            assert (
                supplemental["verified"] is False
                and supplemental["followers_count"] is None
            )
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_partner_sql_snapshot_is_read_only_repeatable_without_user_lock(
    collaboration_pg,
):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from ugc_bot.infrastructure.db.repositories.partner_view import (
        SqlAlchemyPartnerViewRepository,
    )

    container, _, _ = await setup(collaboration_pg, "client", "telegram")
    factory, _, _, clock, data = collaboration_pg
    try:
        async with factory.begin() as db:
            read = await SqlAlchemyPartnerViewRepository().read(
                data["client"],
                clock.at + timedelta(days=1),
                network_page=0,
                assignment_page=0,
                session=db,
            )
            assert read.actor_id == data["client"]
            assert (
                await db.scalar(text("SHOW transaction_isolation"))
                == "repeatable read"
            )
            assert await db.scalar(text("SHOW transaction_read_only")) == "on"
            async with factory.begin() as writer:
                user = await writer.scalar(
                    select(UserModel)
                    .where(UserModel.user_id == data["client"])
                    .with_for_update(nowait=True)
                )
                user.language = "kk"
            assert (
                await db.scalar(
                    select(UserModel.language).where(
                        UserModel.user_id == data["client"]
                    )
                )
                == "en"
            )
        async with factory.begin() as db:
            missing = await SqlAlchemyPartnerViewRepository().read(
                uuid4(), clock.at, network_page=0, assignment_page=0, session=db
            )
            assert missing is None
        with pytest.raises(DBAPIError, match="read.only transaction"):
            async with factory.begin() as db:
                await SqlAlchemyPartnerViewRepository().read(
                    data["client"],
                    clock.at + timedelta(days=1),
                    network_page=0,
                    assignment_page=0,
                    session=db,
                )
                await db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == data["client"])
                    .values(language="ru")
                )
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_partner_current_grade_pages_do_not_change_payment_snapshot(
    collaboration_pg,
):
    from sqlalchemy import insert

    from ugc_bot.domain.enums import AudienceGender, UserStatus

    container, config, body = await setup(
        collaboration_pg, "client", "telegram"
    )
    factory, _, _, clock, data = collaboration_pg
    source = await basis(collaboration_pg)
    async with factory.begin() as db:
        await FinancialLedgerService(
            SqlAlchemyFinancialLedgerRepository()
        ).issue(source, recorded_at=clock.at, session=db)
        ids = [uuid4() for _ in range(99)]
        await db.execute(
            insert(UserModel),
            [
                {
                    "user_id": uid,
                    "username": "private-network-name",
                    "status": UserStatus.ACTIVE,
                    "messenger_type": MessengerType.TELEGRAM,
                }
                for uid in ids
            ],
        )
        await db.execute(
            insert(BloggerProfileModel),
            [
                {
                    "user_id": uid,
                    "instagram_url": f"https://instagram.com/{uid.hex}",
                    "instagram_user_id": uid.hex,
                    "confirmed": True,
                    "topics": {},
                    "audience_gender": AudienceGender.ALL,
                    "audience_age_min": 18,
                    "audience_age_max": 65,
                    "audience_geo": "synthetic",
                    "price": 1,
                }
                for uid in ids
            ],
        )
        await db.execute(
            insert(UserReferralBindingModel),
            [
                {"referrer_user_id": data["client"], "referred_user_id": uid}
                for uid in ids
            ],
        )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application(container, config)),
            base_url="http://testserver",
        ) as client:
            result = await client.post(PATH, json=body)
            assert result.status_code == 200, result.text
            view = result.json()
            assert view["grade"]["verified_creators"] == 100
            assert view["grade"]["tier_rate_bps"] == 1200
            assert view["grade"]["remaining"] == 100
            assert view["network"]["total"] == 100
            assert (
                len(view["network"]["members"]) == 20
                and view["network"]["has_more"]
            )
            second = (
                await client.post(PATH, json={**body, "network_page": 1})
            ).json()
            assert not {
                m["member_id"] for m in view["network"]["members"]
            }.intersection(m["member_id"] for m in second["network"]["members"])
            assert (
                view["financial"]["history"]["entries"][0]["rate_bps"] == 1000
            )
            assert "private-network-name" not in result.text
            assert (
                await client.post(
                    PATH,
                    json={**body, "init_data": body["init_data"][:-1] + "x"},
                )
            ).status_code == 401
            assert (
                await client.post(
                    PATH + "?recipient_id=" + str(data["manager"]), json=body
                )
            ).status_code == 422
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table,section",
    [
        ("financial_movements", "financial"),
        ("financial_override_events", "overrides"),
        ("financial_collaborations", "assignments"),
    ],
)
async def test_partner_missing_financial_source_keeps_network_without_zeros(
    collaboration_pg,
    table,
    section,
):
    from sqlalchemy import text

    container, config, body = await setup(
        collaboration_pg, "client", "telegram"
    )
    factory = collaboration_pg[0]
    async with factory.begin() as db:
        await db.execute(
            text(f"ALTER TABLE {table} RENAME TO partner_hidden_source")
        )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application(container, config)),
            base_url="http://testserver",
        ) as client:
            result = await client.post(PATH, json=body)
            assert result.status_code == 200, result.text
            assert result.json()[section]["state"] == "unavailable"
            if section == "financial":
                assert result.json()[section]["balances"] is None
            assert result.json()["network"]["total"] == 1
    finally:
        async with factory.begin() as db:
            await db.execute(
                text(f"ALTER TABLE partner_hidden_source RENAME TO {table}")
            )
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_partner_overrides_are_scoped_and_expire_without_private_reason(
    collaboration_pg,
):
    from ugc_bot.application.override_ports import CreateRateOverride
    from ugc_bot.application.services.rate_override_service import (
        RateOverrideService,
    )
    from ugc_bot.infrastructure.db.repositories.rate_overrides import (
        SqlAlchemyRateOverrideRepository,
    )

    container, config, body = await setup(
        collaboration_pg, "client", "telegram"
    )
    factory, _, _, clock, data = collaboration_pg
    policy = (await basis(collaboration_pg)).policy_version
    async with factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == data["client"])
            .values(admin=True)
        )
        await RateOverrideService(
            SqlAlchemyRateOverrideRepository(), clock
        ).execute(
            CreateRateOverride(
                operation_key="partner-rate:" + str(data["client"]),
                actor_id=data["client"],
                recipient_id=data["client"],
                side="creator",
                policy_version=policy,
                reason="PRIVATE AGREEMENT REASON",
                rate_bps=2500,
                effective_from=clock.at,
                effective_until=clock.at + timedelta(days=1),
            ),
            session=db,
        )
    app = application(container, config)
    app.state.dispatcher["partner_view_service"].clock = clock
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            result = await client.post(PATH, json=body)
            assert result.status_code == 200, result.text
            overrides = result.json()["overrides"]["entries"]
            assert (
                len(overrides) == 1 and overrides[0]["policy_version"] == policy
            )
            assert (
                overrides[0]["rate_bps"] == 2500
                and overrides[0]["side"] == "creator"
            )
            assert "PRIVATE AGREEMENT" not in result.text
            clock.at += timedelta(days=1)
            assert (await client.post(PATH, json=body)).json()["overrides"][
                "entries"
            ] == []
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_partner_manager_links_require_current_order_role(
    collaboration_pg,
):
    from sqlalchemy import delete

    from tests.postgres_financial.test_collaboration_persistence import start
    from ugc_bot.infrastructure.db.models import ManagerOrderModel

    container, config, body = await setup(
        collaboration_pg, "manager", "telegram"
    )
    await start(collaboration_pg)
    factory, _, _, _, data = collaboration_pg
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application(container, config)),
            base_url="http://testserver",
        ) as client:
            first = await client.post(PATH, json=body)
            assert first.status_code == 200, first.text
            assert first.json()["assignments"]["entries"][0][
                "assignment_id"
            ] == str(data["assignment"])
            async with factory.begin() as db:
                await db.execute(
                    delete(ManagerOrderModel).where(
                        ManagerOrderModel.user_id == data["manager"]
                    )
                )
            second = await client.post(PATH, json=body)
            assert second.status_code == 200
            assert second.json()["assignments"]["entries"] == []
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_partner_missing_wallet_with_real_journal_is_not_silent_zero(
    collaboration_pg,
):
    from sqlalchemy import delete

    container, config, body = await setup(
        collaboration_pg, "client", "telegram"
    )
    factory, _, _, clock, data = collaboration_pg
    source = await basis(collaboration_pg)
    async with factory.begin() as db:
        await FinancialLedgerService(
            SqlAlchemyFinancialLedgerRepository()
        ).issue(source, recorded_at=clock.at, session=db)
    async with factory.begin() as db:
        await db.execute(
            delete(FinancialWalletModel).where(
                FinancialWalletModel.recipient_id == data["client"]
            )
        )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application(container, config)),
            base_url="http://testserver",
        ) as client:
            result = await client.post(PATH, json=body)
            assert result.status_code == 200, result.text
            assert result.json()["financial"]["state"] == "mismatch"
            assert result.json()["financial"]["projection"] is None
            assert result.json()["financial"]["balances"]["pending"] == "5000"
    finally:
        await container.session_factory.kw["bind"].dispose()
