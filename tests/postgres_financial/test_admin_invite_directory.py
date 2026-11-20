"""Bounded people searches use real identity fields and preserve all facts."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.postgres_financial.test_creator_social import seed_profile
from tests.postgres_financial.test_invite_partners import partner, work_manager
from tests.postgres_financial.test_telegram_order_summary import (
    financial_pg_engine,
    intake_env,
    paid_order,
)
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.invite_partner_models import PARTNERS
from ugc_bot.infrastructure.db.manager_application_models import APPLICATIONS
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    InstagramStatsModel,
    ManagerOrderModel,
    UserModel,
    UserReferralBindingModel,
)

__all__ = ["financial_pg_engine", "intake_env"]


def counts(engine):
    with Session(engine) as db:
        return [
            db.scalar(select(func.count()).select_from(table))
            for table in (
                INVITES,
                PARTNERS,
                ManagerOrderModel,
                UserReferralBindingModel,
            )
        ]


def setup_people(engine):
    at = datetime.now(timezone.utc)
    with Session(engine) as db, db.begin():
        manager = partner(db)
        work_manager(db, manager, at)
        db.get(UserModel, manager).username = str(manager)
        db.get(UserModel, manager).telegram = "anna_work"
        db.execute(
            APPLICATIONS.update()
            .where(APPLICATIONS.c.user_id == manager)
            .values(answers={"name": "Анна Петрова"})
        )
        referrer = partner(db)
        db.get(UserModel, referrer).username = str(referrer)
        db.get(UserModel, referrer).telegram = "oleg_ref"
        db.execute(
            APPLICATIONS.insert().values(
                user_id=referrer,
                state="draft",
                answers={"name": "Олег Иванов"},
                updated_at=at,
            )
        )
        creator = seed_profile(db, stable_id=uuid4().hex)
        db.get(UserModel, creator).username = str(creator)
        db.get(UserModel, creator).telegram = "tt_barskaya"
        db.get(
            BloggerProfileModel, creator
        ).instagram_url = "https://instagram.com/tt_barskaya/"
        db.add(
            InstagramStatsModel(
                user_id=creator,
                raw_response={},
                fetched_at=at,
                full_name="Татьяна Барская",
            )
        )
        db.add(
            UserReferralBindingModel(
                referred_user_id=creator,
                referrer_user_id=referrer,
                created_at=at,
            )
        )
        db.execute(
            UserModel.__table__.insert(),
            [
                dict(
                    user_id=uuid4(),
                    messenger_type="telegram",
                    username=f"Координатор {index:04}",
                    status="active",
                    referral_code=uuid4().hex[:16],
                )
                for index in range(1005)
            ],
        )
        return manager, referrer, creator


@pytest.mark.asyncio
async def test_admin_search_is_bounded_authenticated_and_read_only(
    intake_env, monkeypatch
):
    from ugc_bot.admin.app import create_admin_app

    env = intake_env
    _, oid, _, _, _ = await paid_order(env, interested_creators=0)
    manager, referrer, creator = setup_people(env["pg"])
    for key, value in {
        "DATABASE_URL": env["pg"].url.render_as_string(hide_password=False),
        "BOT_TOKEN": "test-token",
        "ADMIN_USERNAME": "test_admin",
        "ADMIN_PASSWORD": "test_pass",
        "ADMIN_SECRET": "test_secret",
        "FINANCIAL_CORE_ENABLED": "true",
        "CUSTOMER_WORKFLOWS_ENABLED": "true",
        "TELEGRAM_BOT_USERNAME": "example_test_bot",
    }.items():
        monkeypatch.setenv(key, value)
    send = AsyncMock()
    monkeypatch.setattr(
        "ugc_bot.admin.creator_invites.dispatch_customer_contact", send
    )
    before = counts(env["pg"])
    path = f"/admin/orders/{oid}/creator-invites"
    with TestClient(create_admin_app()) as client:
        assert (
            client.get(
                path + "/search", params={"q": "Анна", "kind": "manager"}
            ).status_code
            == 401
        )
        assert (
            client.get(
                path + "/profile", params={"instagram": "tt_barskaya"}
            ).status_code
            == 401
        )
        client.post(
            "/admin/login",
            data={"username": "test_admin", "password": "test_pass"},
        )

        def search(kind, query):
            result = client.get(
                path + "/search", params={"kind": kind, "q": query}
            )
            assert result.status_code == 200
            assert result.headers["cache-control"] == "no-store"
            return result.json()

        result = search("referrer", "Координатор")
        assert len(result["results"]) == 8 and result["more"]
        for query in [
            "Татьяна Бар",
            "@tt_barskaya",
            "https://www.instagram.com/tt_barskaya/",
            "https://www.instagram.com/tt_barskaya/?igsh=example",
            "https://t.me/tt_barskaya",
        ]:
            result = search("creator", query)
            assert [row["id"] for row in result["results"]] == [str(creator)]
            assert result["results"][0]["name"] == "Татьяна Барская"
            assert "Telegram · @tt_barskaya" in result["results"][0]["detail"]
        result = search("manager", "Анна Пет")
        assert result["results"][0]["id"] == str(manager)
        assert result["results"][0]["name"] == "Анна Петрова"
        assert search("manager", "Олег")["results"] == []
        result = search("referrer", "Олег")
        assert result["results"][0]["id"] == str(referrer)
        assert result["results"][0]["name"] == "Олег Иванов"
        for literal in ["%", "\\"]:
            assert search("referrer", literal)["results"] == []
        assert {row["id"] for row in search("referrer", "_")["results"]} == {
            str(manager),
            str(referrer),
        }
        assert search("creator", "")["results"] == []
        assert (
            client.get(
                path + "/search", params={"kind": "everything", "q": "x"}
            ).status_code
            == 422
        )
        assert (
            client.get(
                f"/admin/orders/{uuid4()}/creator-invites/search",
                params={"q": "Анна"},
            ).status_code
            == 404
        )
        profile = client.get(
            path + "/profile",
            params={"instagram": "tt_barskaya", "telegram": "tt_barskaya"},
        )
        assert profile.status_code == 200
        assert profile.json()["referrer"]["id"] == str(referrer)
        assert profile.json()["referrer"]["name"] == "Олег Иванов"
        assert (
            client.get(
                path + "/profile", params={"instagram": "invalid/profile"}
            ).status_code
            == 422
        )
        form = client.get(path)
        assert form.status_code == 200
        assert "Координатор 1000" not in form.text
        assert str(manager) not in form.text and str(referrer) not in form.text
        assert len(form.content) < 35000
    send.assert_not_awaited()
    assert counts(env["pg"]) == before
