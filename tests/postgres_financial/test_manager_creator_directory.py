"""Signed manager directory reads backed by the real referral bindings."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, inspect, text, update
from sqlalchemy.exc import IntegrityError

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.financial_environment import (
    isolated_financial_database,
    upgrade_financial_schema,
)
from tests.postgres_financial.test_collaboration_persistence import (
    collaboration_pg as collaboration_fixture,
)
from tests.postgres_financial.test_partner_view_api import application
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.entities import UserReferralPending
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    ManagerCreatorFollowupModel,
    ManagerOrderModel,
    UserModel,
    UserReferralBindingModel,
    UserReferralPendingModel,
)
from ugc_bot.infrastructure.db.repositories.bot_availability import (
    record_bot_availability,
)
from ugc_bot.infrastructure.db.social_models import SocialAccountModel

collaboration_pg = collaboration_fixture
PATH = "/miniapp/api/manager/invited-creators"


def _creator(user_id, status, *, name="Synthetic creator", telegram=None):
    return UserModel(
        user_id=user_id,
        messenger_type=MessengerType.TELEGRAM,
        username=name,
        telegram=telegram,
        status=status,
    )


def _profile(user_id):
    return BloggerProfileModel(
        user_id=user_id,
        instagram_url=f"https://instagram.com/{user_id.hex[:24]}",
        instagram_user_id=str(user_id.int),
        confirmed=True,
        city="Казань",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=65,
        audience_geo="synthetic",
        price=1,
    )


def test_followup_migration_upgrades_the_deployed_parent(financial_pg_engine):
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="0142_creator_offer_cards",
    ) as engine:
        manager, creator = uuid4(), uuid4()
        assert not inspect(engine).has_table("manager_creator_followups")
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO users "
                    "(user_id,username,messenger_type,status) "
                    "VALUES (:manager,'manager','telegram','active'),"
                    "(:creator,'creator','telegram','active')"
                ),
                {"manager": manager, "creator": creator},
            )
        upgrade_financial_schema(
            engine, target_revision="0143_manager_creator_followups"
        )
        with engine.begin() as db:
            assert db.scalar(text("SELECT count(*) FROM users")) == 2
            assert db.scalar(
                text("SELECT version_num FROM alembic_version")
            ) == ("0143_manager_creator_followups")
            db.execute(
                text(
                    "INSERT INTO manager_creator_followups "
                    "(manager_id,creator_id,remind_at) "
                    "VALUES (:manager,:creator,now()+interval '1 day')"
                ),
                {"manager": manager, "creator": creator},
            )
        with pytest.raises(IntegrityError), engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO manager_creator_followups "
                    "(manager_id,creator_id,remind_at) "
                    "VALUES (:manager,:creator,now())"
                ),
                {"manager": manager, "creator": creator},
            )
        assert "creator_offer_card" in {
            column["name"] for column in inspect(engine).get_columns("orders")
        }


@pytest.mark.asyncio
async def test_first_invite_is_fixed_and_existing_creator_cannot_be_claimed(
    collaboration_pg,
):
    factory, _, _, _, seeded = collaboration_pg
    existing = seeded["creator"]
    first, second, newcomer = (uuid4() for _ in range(3))
    first_code, second_code = first.hex[:12], second.hex[:12]
    async with factory.begin() as db:
        for user_id, code in ((first, first_code), (second, second_code)):
            user = _creator(user_id, UserStatus.ACTIVE)
            user.referral_code = code
            db.add(user)
        db.add(_creator(newcomer, UserStatus.ACTIVE))

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "telegram-test-token",
            "DATABASE_URL": factory.kw["bind"].url.render_as_string(
                hide_password=False
            ),
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
        }
    )
    container = Container(config)
    services = container.build_bot_services()
    referrals = services["referral_service"]
    signup = services["blogger_registration_service"]
    pending = services["user_referral_pending_repo"]
    bindings = services["user_referral_binding_repo"]
    try:
        assert not await referrals.save_pending_referral(existing, first_code)
        assert await pending.get_by_user(existing) is None

        # Simulate a stale pending record written before the guard existed.
        now = datetime.now(timezone.utc)
        async with factory.begin() as db:
            db.add(
                UserReferralPendingModel(
                    user_id=existing, referrer_user_id=first, created_at=now
                )
            )
        await signup.confirm_blogger_agreement(existing)
        assert await pending.get_by_user(existing) is None
        assert await bindings.get_by_referred_user(existing) is None

        assert await referrals.save_pending_referral(newcomer, first_code)
        assert await referrals.save_pending_referral(newcomer, second_code)
        # Also exercise insert conflict handling independent of the lookup.
        await pending.save(UserReferralPending(newcomer, second, now))
        async with factory.begin() as db:
            db.add(_profile(newcomer))
        await signup.confirm_blogger_agreement(newcomer)
        assert await referrals.save_pending_referral(newcomer, second_code)
        binding = await bindings.get_by_referred_user(newcomer)
        assert binding is not None and binding.referrer_user_id == first
        assert await pending.get_by_user(newcomer) is None
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_manager_directory_checks_current_binding_on_both_messengers(
    collaboration_pg,
):
    factory, _, _, clock, seeded = collaboration_pg
    first = seeded["manager"]
    second, blocked, paused, unbound = (uuid4() for _ in range(4))
    active = seeded["creator"]
    externals = {
        actor: uuid4().int % 10**12 + 1
        for actor in (first, second, seeded["client"])
    }
    async with factory.begin() as db:
        db.add(
            UserModel(
                user_id=second,
                username="Second manager",
                status=UserStatus.ACTIVE,
                messenger_type=MessengerType.MAX,
                max_id=str(externals[second]),
            )
        )
        for actor in (first, seeded["client"]):
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == actor)
                .values(telegram_id=str(externals[actor]))
            )
        blocked_creator = _creator(
            blocked, UserStatus.ACTIVE, telegram="own_special"
        )
        blocked_creator.telegram_id = "743921"
        db.add_all(
            [
                blocked_creator,
                _creator(paused, UserStatus.PAUSE, name="Мария Казанцева"),
                _creator(unbound, UserStatus.BOT_BLOCKED),
            ]
        )
        await db.flush()
        db.add_all(
            [_profile(creator) for creator in (blocked, paused, unbound)]
        )
        db.add(
            ManagerOrderModel(
                user_id=second,
                order_id=seeded["order"],
                created_at=clock.at,
                updated_at=clock.at,
            )
        )
        db.add_all(
            UserReferralBindingModel(
                referrer_user_id=manager, referred_user_id=creator
            )
            for manager, creator in (
                (first, active),
                (first, paused),
                (second, blocked),
            )
        )
        db.add(
            SocialAccountModel(
                account_id=uuid4(),
                user_id=blocked,
                platform="youtube",
                url="https://www.youtube.com/@synthetic",
                handle="@synthetic",
                work_format=WorkFormat.UGC_ONLY,
                created_at=clock.at,
                updated_at=clock.at,
            )
        )
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "telegram-test-token",
            "MAX_BOT_TOKEN": "max-test-token",
            "DATABASE_URL": factory.kw["bind"].url.render_as_string(
                hide_password=False
            ),
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
        }
    )
    container = Container(config)
    assert await record_bot_availability(
        container.transaction_manager,
        platform=MessengerType.TELEGRAM,
        external_id="743921",
        occurred_at=clock.at,
    )
    transport = httpx.ASGITransport(app=application(container, config))

    def signed(actor, platform="telegram"):
        return {
            "init_data": generate_init_data(
                f"{platform}-test-token", externals[actor], "synthetic"
            ),
            "platform": platform,
        }

    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:

            async def post(auth, suffix="", **params):
                response = await client.post(
                    PATH + suffix, json={**auth, **params}
                )
                assert response.headers["cache-control"] == "no-store"
                return response

            async def listed(auth, **params):
                response = await post(auth, **params)
                assert response.status_code == 200, response.json()
                return {
                    row["creator_id"] for row in response.json()["creators"]
                }

            telegram, max_app = signed(first), signed(second, "max")
            assert await listed(telegram) == {str(active), str(paused)}
            assert await listed(max_app) == {str(blocked)}
            assert await listed(telegram, bot_unavailable=True) == set()
            assert await listed(max_app, bot_unavailable=True) == {str(blocked)}
            assert await listed(max_app, page=1) == set()
            assert await listed(telegram, q="мария") == {str(paused)}
            assert await listed(telegram, q="  КАЗАНЬ ") == {str(paused)}
            assert await listed(
                max_app, q="  КАЗАНЬ ", bot_unavailable=True
            ) == {str(blocked)}
            assert await listed(telegram, q="@own_special") == set()
            assert await listed(max_app, q="@Own_Special") == {str(blocked)}
            assert await listed(max_app, q=blocked.hex[:12]) == {str(blocked)}
            assert await listed(max_app, q="Мария") == set()
            assert await listed(max_app, q="%") == set()
            assert (await post(max_app, q="x" * 121)).status_code == 422
            assert (
                await post(telegram, instagram="unknown")
            ).status_code == 422
            assert await listed(telegram, instagram="verified") == {str(paused)}
            assert await listed(telegram, instagram="unverified") == {
                str(active)
            }
            due = (await post(telegram, instagram="due")).json()
            assert due["followup_count"] == 1
            assert {row["creator_id"] for row in due["creators"]} == {
                str(active)
            }
            assert due["creators"][0]["telegram_url"] is None
            beyond_page = (await post(telegram, instagram="due", page=1)).json()
            assert beyond_page == {
                "creators": [],
                "has_more": False,
                "followup_count": 1,
            }

            endpoint = f"/{active}/followup"
            assert (
                await post(max_app, endpoint, action="tomorrow")
            ).status_code == 404
            assert (
                await post(telegram, f"/{paused}/followup", action="tomorrow")
            ).status_code == 404
            response = await post(telegram, endpoint, action="tomorrow")
            assert response.status_code == 200, response.json()
            tomorrow = datetime.fromisoformat(response.json()["remind_at"])
            assert (
                timedelta(hours=23)
                < tomorrow - datetime.now(timezone.utc)
                < timedelta(hours=25)
            )
            response = await post(telegram, endpoint, action="contacted")
            assert response.status_code == 200, response.json()
            remind_at = datetime.fromisoformat(response.json()["remind_at"])
            assert (
                timedelta(hours=23) < remind_at - tomorrow < timedelta(hours=25)
            )
            assert await listed(telegram, instagram="due") == set()
            assert await listed(telegram, instagram="unverified") == {
                str(active)
            }

            async with factory.begin() as db:
                await db.execute(
                    update(ManagerCreatorFollowupModel)
                    .where(ManagerCreatorFollowupModel.creator_id == active)
                    .values(remind_at=func.now() - timedelta(seconds=1))
                )
            assert await listed(telegram, instagram="due") == {str(active)}
            async with factory.begin() as db:
                await db.execute(
                    update(BloggerProfileModel)
                    .where(BloggerProfileModel.user_id == active)
                    .values(confirmed=True, instagram_user_id=str(active.int))
                )
            assert await listed(telegram, instagram="due") == set()
            assert (
                await post(telegram, endpoint, action="contacted")
            ).status_code == 404

            assert (await post(telegram, f"/{active}")).status_code == 200
            not_found = await post(telegram, f"/{blocked}")
            absent = await post(telegram, f"/{unbound}")
            assert not_found.status_code == absent.status_code == 404
            assert not_found.json() == absent.json()
            assert (await post(max_app, f"/{active}")).status_code == 404
            assert (await post(signed(seeded["client"]))).status_code == 403
            assert (
                await post(telegram, manager_id=str(second))
            ).status_code == 422
            assert (
                await post({**max_app, "platform": "telegram"})
            ).status_code == 401

            response = await post(max_app, f"/{blocked}")
            assert response.status_code == 200, response.json()
            assert response.json() == {
                "creator_id": str(blocked),
                "name": "Synthetic creator",
                "city": "Казань",
                "status": "bot_blocked",
                "instagram_verified": True,
                "telegram_url": "https://t.me/own_special",
                "followup_due": False,
                "remind_at": None,
                "links": [
                    {
                        "label": "Instagram",
                        "url": f"https://www.instagram.com/{blocked.hex[:24]}",
                    },
                    {
                        "label": "YouTube",
                        "url": "https://www.youtube.com/@synthetic",
                    },
                ],
            }
            async with factory.begin() as db:
                await db.execute(
                    update(UserReferralBindingModel)
                    .where(UserReferralBindingModel.referred_user_id == blocked)
                    .values(referrer_user_id=first)
                )
            assert (await post(max_app, f"/{blocked}")).status_code == 404
            assert await listed(
                telegram, q="@own_special", bot_unavailable=True
            ) == {str(blocked)}
            assert (
                await listed(max_app, q="@own_special", bot_unavailable=True)
                == set()
            )
    finally:
        await container.session_factory.kw["bind"].dispose()
